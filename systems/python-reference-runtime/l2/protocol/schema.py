"""Protocol v1 JSON Schemas — machine-readable contract for the TS mirror.

Draft-07 JSON Schemas describing the envelope and each message kind's
payload. The TypeScript rewrite mirrors these directly (zod / io-ts), so
contract drift between the Python reference and the TS port is caught by
shared expectations instead of ad-hoc structs.
"""

from __future__ import annotations

from typing import Any

from l2.protocol.records import RECORD_SCHEMA_VERSION, RECORD_TYPES

ENVELOPE_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "praxis/l2/protocol/v1/envelope",
    "title": "Praxis L2 Protocol v1 Envelope",
    "type": "object",
    "required": ["v", "session_id", "seq", "ts", "kind", "payload"],
    "properties": {
        "v": {"const": 1},
        "session_id": {"type": "string", "minLength": 1},
        "seq": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
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
            "last_acked": {"type": "integer", "minimum": -1, "maximum": 9007199254740991},
        },
    },
    "ack": {
        "$id": "praxis/l2/protocol/v1/payload/ack",
        "type": "object",
        "required": ["ack_seq"],
        "properties": {"ack_seq": {"type": "integer", "minimum": 0, "maximum": 9007199254740991}},
    },
}

RECORD_ENVELOPE_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "praxis/l2/protocol/v1/record",
    "title": "Praxis L2/L3A Protocol v1 Record",
    "type": "object",
    "required": ["record_type", "schema_version", "data"],
    "properties": {
        "record_type": {
            "enum": sorted(RECORD_TYPES),
        },
        "schema_version": {"const": RECORD_SCHEMA_VERSION},
        "data": {"type": "object"},
    },
    "additionalProperties": True,
}

RECORD_DATA_SCHEMAS: dict[str, dict[str, Any]] = {
    "session_identity": {
        "$id": "praxis/l2/protocol/v1/record/session_identity",
        "type": "object",
        "required": ["session_id", "terminal_id", "process_id"],
        "properties": {
            "session_id": {"type": "string", "minLength": 1},
            "terminal_id": {"type": "string", "minLength": 1},
            "process_id": {"type": "string", "minLength": 1},
            "user_id": {"type": "string"},
            "role": {"type": "string"},
            "cell_id": {"type": "string"},
            "memory_scope": {"type": "string"},
        },
    },
    "event_envelope": {
        "$id": "praxis/l2/protocol/v1/record/event_envelope",
        "type": "object",
        "required": ["event_id", "session_id", "seq", "event_type", "payload"],
        "properties": {
            "event_id": {"type": "string", "minLength": 1},
            "session_id": {"type": "string", "minLength": 1},
            "seq": {"type": "integer", "minimum": 0},
            "event_type": {"type": "string", "minLength": 1},
            "payload": {"type": "object"},
            "input_seq": {"type": ["integer", "null"], "minimum": 1},
            "trace_id": {"type": "string"},
            "ts": {"type": "number"},
        },
    },
    "session_message": {
        "$id": "praxis/l2/protocol/v1/record/session_message",
        "type": "object",
        "required": ["message_id", "session_id", "input_seq", "role", "content"],
        "properties": {
            "message_id": {"type": "string", "minLength": 1},
            "session_id": {"type": "string", "minLength": 1},
            "input_seq": {"type": "integer", "minimum": 1},
            "role": {"type": "string", "minLength": 1},
            "content": {"type": "string"},
            "trace_id": {"type": "string"},
            "ts": {"type": "number"},
        },
    },
    "tool_failure": {
        "$id": "praxis/l2/protocol/v1/record/tool_failure",
        "type": "object",
        "required": [
            "failure_id",
            "session_id",
            "input_seq",
            "tool_name",
            "error_kind",
            "message",
            "retryable",
        ],
        "properties": {
            "failure_id": {"type": "string", "minLength": 1},
            "session_id": {"type": "string", "minLength": 1},
            "input_seq": {"type": "integer", "minimum": 1},
            "tool_name": {"type": "string", "minLength": 1},
            "error_kind": {"type": "string", "minLength": 1},
            "message": {"type": "string"},
            "retryable": {"type": "boolean"},
            "trace_id": {"type": "string"},
            "ts": {"type": "number"},
        },
    },
    "decision_summary": {
        "$id": "praxis/l2/protocol/v1/record/decision_summary",
        "type": "object",
        "required": ["decision_id", "session_id", "input_seq", "summary", "outcome"],
        "properties": {
            "decision_id": {"type": "string", "minLength": 1},
            "session_id": {"type": "string", "minLength": 1},
            "input_seq": {"type": "integer", "minimum": 1},
            "summary": {"type": "string"},
            "outcome": {"type": "string", "minLength": 1},
            "evidence_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "trace_id": {"type": "string"},
            "ts": {"type": "number"},
        },
    },
    "evidence_ref": {
        "$id": "praxis/l2/protocol/v1/record/evidence_ref",
        "type": "object",
        "required": ["evidence_id", "session_id", "input_seq", "kind", "locator"],
        "properties": {
            "evidence_id": {"type": "string", "minLength": 1},
            "session_id": {"type": "string", "minLength": 1},
            "input_seq": {"type": "integer", "minimum": 1},
            "kind": {"type": "string", "minLength": 1},
            "locator": {"type": "string", "minLength": 1},
            "digest": {"type": "string"},
            "trace_id": {"type": "string"},
            "metadata": {"type": "object"},
        },
    },
}
