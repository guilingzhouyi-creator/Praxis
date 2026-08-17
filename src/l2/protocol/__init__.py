"""Protocol v1 — Unified Session Data Layer reference package.

Language-agnostic wire contract for the L2 shell engine (see
docs/architecture/l2-shell-engine.md). Pure Python reference so the planned
TypeScript mirror (parser/dispatcher/session/bridge) can be implemented and
tested against a stable, side-effect-free baseline.

Modules:
  envelope — message construction/validation/encoding + Outbox/SessionCursor
  schema   — JSON Schema machine-readable contract (TS zod/io-ts mirror)
  host     — JSONL stdio bridge over the existing l2.l2_shell.dispatch
"""

from __future__ import annotations

from l2.protocol.envelope import (
    KIND_ACK,
    KIND_COMMAND,
    KIND_CONTROL,
    KIND_EVENT,
    KIND_INTENT,
    KIND_RESULT,
    KIND_STREAM_CHUNK,
    KINDS,
    OUTBOX_MAXLEN,
    PROTOCOL_VERSION,
    Outbox,
    SessionCursor,
    decode_message,
    encode_message,
    make_message,
    validate_message,
)
from l2.protocol.schema import ENVELOPE_JSON_SCHEMA, KIND_PAYLOAD_SCHEMAS

__all__ = [
    "KIND_ACK",
    "KIND_COMMAND",
    "KIND_CONTROL",
    "KIND_EVENT",
    "KIND_INTENT",
    "KIND_RESULT",
    "KIND_STREAM_CHUNK",
    "KINDS",
    "OUTBOX_MAXLEN",
    "PROTOCOL_VERSION",
    "Outbox",
    "SessionCursor",
    "decode_message",
    "encode_message",
    "make_message",
    "validate_message",
    "ENVELOPE_JSON_SCHEMA",
    "KIND_PAYLOAD_SCHEMAS",
]
