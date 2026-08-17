"""Protocol v1 stdio host - JSONL bridge over the existing L2 engine.

Runs as a module (python -m l2.protocol.host): reads protocol v1 envelopes
from stdin (one JSON object per line), writes result/ack envelopes to
stdout. This is the Python reference peer for the planned TypeScript
bridge.ts; it reuses the existing l2.l2_shell.dispatch unchanged - no
engine modification, no behavior change, purely additive transport.
"""

from __future__ import annotations

import shlex
import sys
from typing import TextIO

from l2.protocol.envelope import (
    CONTROL_ACK,
    CONTROL_ATTACH,
    CONTROL_DETACH,
    CONTROL_RECOVERY,
    CONTROL_RESUME,
    KIND_ACK,
    KIND_COMMAND,
    KIND_CONTROL,
    KIND_EVENT,
    KIND_INTENT,
    KIND_RESULT,
    Outbox,
    decode_message,
    encode_message,
    make_message,
)


def _dispatch_text(text: str, session) -> dict:
    """Route one input line through the existing engine (unchanged)."""
    from l2.l2_shell import dispatch

    try:
        return dispatch(text, session)
    except Exception as e:  # pragma: no cover - defensive bridge boundary
        return {"success": False, "error": str(e)}


class ProtocolHost:
    """Process one input envelope into output envelopes (injectable, no globals)."""

    def __init__(self) -> None:
        self._sessions: dict[str, object] = {}
        self._outboxes: dict[str, Outbox] = {}
        self._seqs: dict[str, int] = {}

    def _next_seq(self, session_id: str) -> int:
        """Return the next outbound sequence id for a session."""
        next_seq = self._seqs.get(session_id, 0) + 1
        self._seqs[session_id] = next_seq
        return next_seq

    def _get_outbox(self, session_id: str) -> Outbox:
        """Return the bounded replay window for a session."""
        if session_id not in self._outboxes:
            self._outboxes[session_id] = Outbox()
        return self._outboxes[session_id]

    def _emit(self, kind: str, payload: dict, session_id: str, trace_id: str = "") -> dict:
        """Build one outbound envelope, record it in the outbox, return it."""
        msg = make_message(session_id, self._next_seq(session_id), kind, payload, trace_id=trace_id)
        self._get_outbox(session_id).append(msg)
        return msg

    def _get_session(self, session_id: str) -> object:
        """Return the in-process ShellSession for an id, creating it lazily."""
        if session_id not in self._sessions:
            from l2.shells.session import ShellSession

            self._sessions[session_id] = ShellSession(shell="protocol", session_id=session_id)
        return self._sessions[session_id]

    def handle(self, line: str) -> list[dict]:
        """Handle one input line; returns zero or more output envelopes."""
        msg, err = decode_message(line)
        if err is not None:
            return [self._emit(KIND_RESULT, {"success": False, "error": err}, "-")]
        session_id = msg["session_id"]
        trace_id = msg.get("trace_id", "")
        kind = msg["kind"]
        payload = msg["payload"]
        out: list[dict] = []
        if kind == KIND_COMMAND:
            name = str(payload.get("name", ""))
            args = [str(a) for a in payload.get("args", [])]
            if not name:
                out.append(
                    self._emit(KIND_RESULT, {"success": False, "error": "command name required"}, session_id, trace_id)
                )
            else:
                text = "/" + name + (" " + shlex.join(args) if args else "")
                result = _dispatch_text(text, self._get_session(session_id))
                out.append(self._emit(KIND_RESULT, result, session_id, trace_id))
        elif kind == KIND_INTENT:
            text = str(payload.get("text", ""))
            result = _dispatch_text(text, self._get_session(session_id))
            out.append(self._emit(KIND_RESULT, result, session_id, trace_id))
        elif kind == KIND_CONTROL:
            out.extend(self._handle_control(payload, session_id, trace_id))
        elif kind == KIND_ACK:
            self._get_outbox(session_id).ack(payload["ack_seq"])
            return []
        else:
            out.append(
                self._emit(
                    KIND_RESULT, {"success": False, "error": f"host does not serve kind: {kind}"}, session_id, trace_id
                )
            )
        # Acknowledge every accepted input so the client cursor can advance.
        out.append(
            make_message(session_id, self._next_seq(session_id), KIND_ACK, {"ack_seq": msg["seq"]}, trace_id=trace_id)
        )
        return out

    def _handle_control(self, payload: dict, session_id: str, trace_id: str) -> list[dict]:
        """Process control envelopes (attach/detach/resume/recovery)."""
        op = str(payload.get("op", ""))
        target = str(payload.get("session_id", session_id))
        if op == CONTROL_ATTACH:
            self._get_session(target)
            return [
                self._emit(
                    KIND_EVENT, {"name": "session.attached", "data": {"session_id": target}}, session_id, trace_id
                )
            ]
        if op == CONTROL_DETACH:
            return [
                self._emit(
                    KIND_EVENT, {"name": "session.detached", "data": {"session_id": target}}, session_id, trace_id
                )
            ]
        if op == CONTROL_ACK:
            self._get_outbox(target).ack(payload.get("last_acked", -1))
            return []
        if op in (CONTROL_RESUME, CONTROL_RECOVERY):
            self._get_session(target)
            outbox = self._get_outbox(target)
            outbox.ack(payload.get("last_acked", -1))
            replay = outbox.unacked()
            return [
                self._emit(
                    KIND_EVENT,
                    {"name": "session.recovered", "data": {"session_id": target, "replay": replay}},
                    target,
                    trace_id,
                )
            ]
        return [self._emit(KIND_RESULT, {"success": False, "error": f"unknown control op: {op}"}, session_id, trace_id)]

    def run(self, stdin: TextIO, stdout: TextIO) -> int:
        """Read JSONL envelopes from stdin, write responses to stdout."""
        count = 0
        for raw in stdin:
            line = raw.strip()
            if not line:
                continue
            for out in self.handle(line):
                stdout.write(encode_message(out) + "\n")
                stdout.flush()
            count += 1
        return count


def main() -> int:
    """Run the stdio host (python -m l2.protocol.host)."""
    host = ProtocolHost()
    return host.run(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
