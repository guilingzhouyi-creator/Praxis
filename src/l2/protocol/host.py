"""Protocol v1 stdio host - JSONL bridge over the existing L2 engine.

Runs as a module (python -m l2.protocol.host): reads protocol v1 envelopes
from stdin (one JSON object per line), writes result/ack envelopes to
stdout. This is the Python reference peer for the planned TypeScript
bridge.ts; it reuses the existing l2.l2_shell.dispatch unchanged - no
engine modification, no behavior change, purely additive transport.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import shlex
import sys
import threading
from typing import Any, TextIO

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
    SessionCursor,
    decode_message,
    encode_message,
    make_message,
    validate_message,
)
from l2.protocol.records import SessionIdentity

_DISPATCH_LOCK = threading.Lock()


def _dispatch_text(text: str, session) -> dict:
    """Route one input line through the existing engine (unchanged).

    Legacy handler ``print()`` output (e.g. status/clear rendering) is
    captured into a ``rendered`` payload field so the JSONL stream stays
    clean and the text reaches protocol clients as data. The capture lock
    serializes dispatches because ``redirect_stdout`` is process-global and
    web mode is threaded.
    """
    from l2.l2_shell import dispatch

    buf = io.StringIO()
    try:
        with _DISPATCH_LOCK, contextlib.redirect_stdout(buf):
            result = dispatch(text, session)
    except Exception as e:  # pragma: no cover - defensive bridge boundary
        return {"success": False, "error": str(e)}
    out = dict(result) if isinstance(result, dict) else {"success": False, "error": str(result)}
    rendered = buf.getvalue()
    if rendered:
        out["rendered"] = rendered
    return out


class ProtocolHost:
    """Process one input envelope into output envelopes (injectable, no globals).

    TS counterpart: ``src/engine/bridge.ts`` ProtocolBridge — its
    command/attach/ack/replay methods map onto ``handle_message`` and the
    control ops here; the TS client speaks this host's protocol v1 and never
    re-implements the session/outbox authority it owns.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, object] = {}
        self._identities: dict[str, SessionIdentity] = {}
        self._cursors: dict[str, SessionCursor] = {}
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

    def _advance_shared_cursor(self, session_id: str) -> None:
        """Advance the shared outbox watermark to the lagging attached view.

        The shared ``Outbox`` cursor is the *minimum* ack across every view
        bound to the session, so one view acknowledging never erases
        messages another view still needs to replay (non-destructive
        multiplexing). A session with no attached views keeps its watermark,
        letting a fresh view replay the whole window from its own cursor.
        """
        min_acked = None
        for cursor in self._cursors.values():
            if cursor.attached and cursor.session_id == session_id:
                min_acked = cursor.last_acked if min_acked is None else min(min_acked, cursor.last_acked)
        if min_acked is not None:
            self._get_outbox(session_id).ack(min_acked)

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
            self._identities[session_id] = SessionIdentity(
                session_id=session_id,
                terminal_id="",
                process_id="",
            )
        return self._sessions[session_id]

    def session_identity(self, session_id: str) -> dict[str, Any]:
        """Return the protocol-shaped identity snapshot for a session.

        ``SessionIdentity`` is the wire value record (mirrored in TS); the
        runtime ShellSession keeps mutable mode/cell/agent state while this
        snapshot carries the stable identity fields consumed by events and
        bridges. terminal/process ownership is injected by the host later.
        """
        self._get_session(session_id)
        return dataclasses.asdict(self._identities[session_id])

    def attach_view(self, view_id: str, session_id: str) -> dict[str, Any]:
        """Bind one frontend view to a session; returns the identity snapshot.

        Multiple views (web, TUI, desktop, SSH, IDE) may attach to the same
        session; each view keeps its own ack cursor while the session outbox
        is shared. ``view_id`` defaults to the session id for single-view
        transports.
        """
        self._get_session(session_id)
        cursor = self._cursors.get(view_id)
        if cursor is None:
            cursor = SessionCursor(view_id=view_id)
            self._cursors[view_id] = cursor
        cursor.attach(session_id)
        return self.session_identity(session_id)

    def detach_view(self, view_id: str) -> None:
        """Unbind a frontend view from its session."""
        cursor = self._cursors.get(view_id)
        if cursor is not None:
            cursor.detach()

    def view_cursor(self, view_id: str) -> dict[str, Any] | None:
        """Return the per-view cursor snapshot (attachment + ack position)."""
        cursor = self._cursors.get(view_id)
        if cursor is None:
            return None
        return dataclasses.asdict(cursor)

    def session_state(self, session_id: str) -> dict[str, Any]:
        """Return the protocol-shaped session snapshot consumed by projections."""
        return {
            "identity": self.session_identity(session_id),
            "events": self._get_outbox(session_id).unacked(),
        }

    def handle(self, line: str) -> list[dict]:
        """Handle one input line; returns zero or more output envelopes."""
        msg, err = decode_message(line)
        if err is not None:
            return [self._emit(KIND_RESULT, {"success": False, "error": err}, "-")]
        return self._handle_validated(msg)

    def handle_message(self, msg: dict[str, Any]) -> list[dict]:
        """Handle one decoded envelope dict; shared by stdio and web modes."""
        violations = validate_message(msg)
        if violations:
            return [self._emit(KIND_RESULT, {"success": False, "error": "; ".join(violations)}, "-")]
        return self._handle_validated(msg)

    def _handle_validated(self, msg: dict[str, Any]) -> list[dict]:
        """Process an already-validated envelope (no re-validation).

        ``handle`` (stdio) validates once during ``decode_message`` and
        ``handle_message`` (web) validates once here, so the hot JSONL path
        avoids a redundant schema pass.
        """
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
            # Per-view acknowledgement: the view cursor advances while the
            # shared outbox watermark follows the lagging view, so messages
            # another view still needs are never erased.
            view_id = str(payload.get("view_id", session_id))
            cursor = self._cursors.get(view_id)
            if cursor is not None:
                cursor.ack(payload["ack_seq"])
                self._advance_shared_cursor(session_id)
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
        view_id = str(payload.get("view_id", target))
        if op == CONTROL_ATTACH:
            identity = self.attach_view(view_id, target)
            return [self._emit(KIND_EVENT, {"name": "session.attached", "data": identity}, session_id, trace_id)]
        if op == CONTROL_DETACH:
            self.detach_view(view_id)
            return [
                self._emit(
                    KIND_EVENT,
                    {"name": "session.detached", "data": {"session_id": target, "view_id": view_id}},
                    session_id,
                    trace_id,
                )
            ]
        if op == CONTROL_ACK:
            cursor = self._cursors.get(view_id)
            if cursor is not None:
                cursor.ack(payload.get("last_acked", -1))
                self._advance_shared_cursor(target)
            return []
        if op in (CONTROL_RESUME, CONTROL_RECOVERY):
            self._get_session(target)
            outbox = self._get_outbox(target)
            cursor = self._cursors.get(view_id)
            if cursor is not None:
                cursor.ack(payload.get("last_acked", -1))
                self._advance_shared_cursor(target)
                replay = outbox.unacked(cursor.last_acked)
            else:
                replay = outbox.unacked(payload.get("last_acked", -1))
            return [
                self._emit(
                    KIND_EVENT,
                    {
                        "name": "session.recovered",
                        "data": {"session_id": target, "view_id": view_id, "replay": replay},
                    },
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
            # Flush once per input line so a burst of outputs batches
            # syscalls instead of flushing per envelope.
            stdout.flush()
            count += 1
        return count


def main() -> int:
    """Run the stdio host (python -m l2.protocol.host)."""
    host = ProtocolHost()
    return host.run(sys.stdin, sys.stdout)


_HOST: ProtocolHost | None = None


def get_protocol_host() -> ProtocolHost:
    """Return the process-wide protocol host (web mode shares its session pool)."""
    global _HOST
    if _HOST is None:
        _HOST = ProtocolHost()
    return _HOST


def reset_protocol_host() -> None:
    """Reset the shared host for tests or a controlled restart."""
    global _HOST
    _HOST = None


if __name__ == "__main__":
    raise SystemExit(main())
