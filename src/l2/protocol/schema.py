"""Protocol v1 JSON Schemas — machine-readable contract for the TS mirror.

Draft-07 JSON Schemas describing the envelope and each message kind's
payload. The TypeScript rewrite mirrors these directly (zod / io-ts), so
contract drift between the Python reference and the TS port is caught by
shared expectations instead of ad-hoc structs.
"""

from __future__ import annotations

from typing import Any

ENVELOPE_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "praxis/l2/protocol/v1/envelope",
    "title": "Praxis L2 Protocol v1 Envelope",
    "type": "object",
    "required": ["v", "session_id", "seq", "ts", "kind", "payload"],
    "properties": {
        "v": {"const": 1},
        "session_id": {"type": "string", "minLength": 1},
        "seq": {"type": "integer", "minimum": 0},
        "ts": {"type": "number"},
        "trace_id": {"type": "string"},
        "kind": {
            "enum": ["ack", "command", "control", "event", "intent", "result", "stream_chunk"],
        },
        "payload": {"type": "object"},
    },
    "additionalProperties": True,
}

KIND_PAYLOAD_SCHEMAS: dict[str, dict[str, Any]] = {
    "command": {
        "$id": "praxis/l2/protocol/v1/payload/command",
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "args": {"type": "array", "items": {"type": "string"}},
        },
    },
    "intent": {
        "$id": "praxis/l2/protocol/v1/payload/intent",
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "target": {"type": "object"},
        },
    },
    "event": {
        "$id": "praxis/l2/protocol/v1/payload/event",
        "type": "object",
        "properties": {"name": {"type": "string"}, "data": {"type": "object"}},
    },
    "result": {
        "$id": "praxis/l2/protocol/v1/payload/result",
        "type": "object",
        "required": ["success"],
        "properties": {"success": {"type": "boolean"}, "error": {"type": "string"}},
    },
    "stream_chunk": {
        "$id": "praxis/l2/protocol/v1/payload/stream_chunk",
        "type": "object",
        "required": ["data"],
        "properties": {"data": {"type": "string"}, "channel": {"type": "string"}},
    },
    "control": {
        "$id": "praxis/l2/protocol/v1/payload/control",
        "type": "object",
        "required": ["op"],
        "properties": {
            "op": {"enum": ["attach", "detach", "resume", "recovery", "ack"]},
            "session_id": {"type": "string"},
            "last_acked": {"type": "integer", "minimum": -1},
        },
    },
    "ack": {
        "$id": "praxis/l2/protocol/v1/payload/ack",
        "type": "object",
        "required": ["ack_seq"],
        "properties": {"ack_seq": {"type": "integer", "minimum": 0}},
    },
}
