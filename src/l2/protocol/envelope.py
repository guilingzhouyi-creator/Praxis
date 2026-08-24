"""Protocol v1 envelope — frozen legacy reference (side-effect free).

DEPRECATED as normative source: `packages/protocol-ts` is the authority
(docs/architecture/l2-shell-engine.md, "Protocol v1 conformance rulings").
This module is kept byte-compatible with the TS/Rust semantics until the
G6 cut-over retires it: non-destructive `Outbox.ack` (R1), finite-`ts`
validation and encoding (R3). Stdlib-only, no singletons, no I/O.
"""

from __future__ import annotations

import json
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION: int = 1

KIND_INTENT = "intent"
KIND_COMMAND = "command"
KIND_EVENT = "event"
KIND_RESULT = "result"
KIND_STREAM_CHUNK = "stream_chunk"
KIND_CONTROL = "control"
KIND_ACK = "ack"
KINDS: frozenset[str] = frozenset(
    {KIND_INTENT, KIND_COMMAND, KIND_EVENT, KIND_RESULT, KIND_STREAM_CHUNK, KIND_CONTROL, KIND_ACK}
)

ENVELOPE_FIELDS: tuple[str, ...] = ("v", "session_id", "seq", "ts", "kind", "payload")

# Bounded replay window per session (recovery reads this, never the past).
OUTBOX_MAXLEN: int = 1024

CONTROL_ATTACH = "attach"
CONTROL_DETACH = "detach"
CONTROL_RESUME = "resume"
CONTROL_RECOVERY = "recovery"
CONTROL_ACK = "ack"
CONTROL_KINDS: frozenset[str] = frozenset(
    {CONTROL_ATTACH, CONTROL_DETACH, CONTROL_RESUME, CONTROL_RECOVERY, CONTROL_ACK}
)

# R4: authorization fields are host-derived (adapter-injected GateRequest
# inputs) and must never travel on the wire.
HOST_DERIVED_FIELDS: tuple[str, ...] = (
    "approved",
    "pre_approved",
    "full_power",
    "harness_auto_approved",
)


def make_message(
    session_id: str,
    seq: int,
    kind: str,
    payload: dict[str, Any],
    *,
    trace_id: str = "",
    ts: float | None = None,
) -> dict[str, Any]:
    """Build a protocol v1 envelope dict from parts."""
    return {
        "v": PROTOCOL_VERSION,
        "session_id": session_id,
        "seq": seq,
        "ts": time.time() if ts is None else ts,
        "trace_id": trace_id,
        "kind": kind,
        "payload": payload,
    }


def validate_message(msg: dict[str, Any]) -> list[str]:
    """Return contract violations as a list; an empty list means valid."""
    errors: list[str] = []
    for field_name in ENVELOPE_FIELDS:
        if field_name not in msg:
            errors.append(f"missing field: {field_name}")
    if errors:
        return errors
    if msg.get("v") != PROTOCOL_VERSION:
        errors.append(f"unsupported version: {msg.get('v')!r}")
    session_id = msg.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        errors.append("session_id must be a non-empty string")
    seq = msg.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        errors.append("seq must be a non-negative integer")
    kind = msg.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        errors.append(f"unknown kind: {kind!r}")
    ts = msg.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts):
        errors.append("ts must be a number")
    if "trace_id" in msg and not isinstance(msg["trace_id"], str):
        errors.append("trace_id must be a string")
    payload = msg.get("payload")
    if not isinstance(payload, dict):
        errors.append("payload must be an object")
    elif isinstance(kind, str) and kind in KINDS:
        errors.extend(_validate_payload(kind, payload))
    return errors


def _validate_payload(kind: str, payload: dict[str, Any]) -> list[str]:
    """Validate the required fields for one message kind."""
    errors: list[str] = []
    if kind in (KIND_COMMAND, KIND_CONTROL) and any(f in payload for f in HOST_DERIVED_FIELDS):
        errors.append("payload carries host-derived authorization fields")
    if kind == KIND_COMMAND:
        name = payload.get("name")
        args = payload.get("args", [])
        if not isinstance(name, str) or not name:
            errors.append("command payload requires a non-empty name")
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            errors.append("command payload args must be a string array")
    elif kind == KIND_INTENT:
        if not isinstance(payload.get("text"), str) or not payload["text"]:
            errors.append("intent payload requires non-empty text")
    elif kind == KIND_RESULT:
        if not isinstance(payload.get("success"), bool):
            errors.append("result payload requires boolean success")
    elif kind == KIND_STREAM_CHUNK:
        if not isinstance(payload.get("data"), str):
            errors.append("stream_chunk payload requires string data")
    elif kind == KIND_CONTROL:
        op = payload.get("op")
        if not isinstance(op, str) or op not in CONTROL_KINDS:
            errors.append(f"control payload has unknown op: {op!r}")
        target = payload.get("session_id")
        if target is not None and (not isinstance(target, str) or not target):
            errors.append("control payload session_id must be a non-empty string")
        last_acked = payload.get("last_acked")
        if last_acked is not None and (
            isinstance(last_acked, bool) or not isinstance(last_acked, int) or last_acked < -1
        ):
            errors.append("control payload last_acked must be an integer >= -1")
    elif kind == KIND_ACK:
        ack_seq = payload.get("ack_seq")
        if isinstance(ack_seq, bool) or not isinstance(ack_seq, int) or ack_seq < 0:
            errors.append("ack payload requires a non-negative integer ack_seq")
    return errors


def encode_message(msg: dict[str, Any]) -> str:
    """Serialize one envelope to a canonical JSON line (stable key order).

    Non-finite floats (NaN/Infinity) raise ValueError: R3 forbids emitting
    frames that strict JSON parsers on the Rust/TS side cannot read.
    """
    return json.dumps(msg, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def decode_message(line: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse one JSON line into a validated envelope; returns (msg, error)."""
    line = line.strip()
    if not line:
        return None, "empty line"
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as e:
        return None, f"invalid json: {e}"
    if not isinstance(msg, dict):
        return None, "envelope must be a JSON object"
    errors = validate_message(msg)
    if errors:
        return None, "; ".join(errors)
    return msg, None


@dataclass
class Outbox:
    """Bounded per-session replay window; unacked messages survive recovery.

    R1 (non-destructive ack): one view's acknowledgement only advances the
    cursor and never erases retained messages another view still needs.
    """

    maxlen: int = OUTBOX_MAXLEN
    _items: deque[dict[str, Any]] = field(default_factory=deque)
    _last_acked: int = -1

    def append(self, msg: dict[str, Any]) -> None:
        """Append an outbound message; evict oldest beyond the cap."""
        self._items.append(msg)
        while len(self._items) > self.maxlen:
            self._items.popleft()

    def ack(self, seq: int) -> None:
        """Advance the acknowledged cursor without dropping retained messages."""
        self._last_acked = max(self._last_acked, seq)

    def unacked(self, after_seq: int | None = None) -> list[dict[str, Any]]:
        """Return the replay window for one view cursor (messages after it)."""
        after = self._last_acked if after_seq is None else after_seq
        return [msg for msg in self._items if msg["seq"] > after]

    @property
    def last_acked(self) -> int:
        """Return the highest acknowledged sequence id."""
        return self._last_acked


@dataclass
class SessionCursor:
    """Per-frontend-view cursor: attachment + acknowledged position."""

    view_id: str
    session_id: str = ""
    last_acked: int = -1
    attached: bool = False

    def attach(self, session_id: str) -> None:
        """Bind the view to a session and mark it attached."""
        self.session_id = session_id
        self.attached = True

    def detach(self) -> None:
        """Unbind the view from its session (marks it unattached)."""
        self.attached = False
