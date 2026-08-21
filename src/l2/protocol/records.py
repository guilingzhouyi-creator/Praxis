"""Versioned TS-neutral records for the L2 and L3A session boundary.

The records are pure data objects with deterministic JSON serialization. They
are deliberately narrower than the internal session files: chain-of-thought,
mutable runtime handles, and Python-specific implementation details do not
cross this boundary.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import MISSING, asdict, dataclass, field, fields
from typing import Any, ClassVar, TypeAlias, cast

RECORD_SCHEMA_VERSION: int = 1


class RecordValidationError(ValueError):
    """Report a malformed, unsupported, or incompatible protocol record."""


def _require_text(value: Any, name: str, *, allow_empty: bool = False) -> None:
    """Validate a text field."""
    if not isinstance(value, str) or (not allow_empty and not value):
        qualifier = "string" if allow_empty else "non-empty string"
        raise RecordValidationError(f"{name} must be a {qualifier}")


def _require_integer(value: Any, name: str, *, minimum: int = 0) -> None:
    """Validate an integer field without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RecordValidationError(f"{name} must be an integer >= {minimum}")


def _require_timestamp(value: Any, name: str = "ts") -> None:
    """Validate a JSON-compatible timestamp."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RecordValidationError(f"{name} must be a number")


def _require_mapping(value: Any, name: str) -> None:
    """Validate an object-shaped field."""
    if not isinstance(value, dict):
        raise RecordValidationError(f"{name} must be an object")


class _ProtocolRecord:
    """Implement common versioning and JSON conversion for protocol records."""

    record_type: ClassVar[str]

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        """Validate record-specific fields."""

    @classmethod
    def _coerce_values(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Normalize decoded values before dataclass construction."""
        return values

    def to_dict(self: Any) -> dict[str, Any]:
        """Return the versioned record envelope as JSON-compatible data."""
        return {
            "record_type": self.record_type,
            "schema_version": RECORD_SCHEMA_VERSION,
            "data": _json_value(asdict(self)),
        }

    @classmethod
    def from_dict(cls: type[Any], raw: dict[str, Any]) -> _ProtocolRecord:
        """Build a record while ignoring unknown fields for forward compatibility."""
        if not isinstance(raw, dict):
            raise RecordValidationError("record must be an object")
        if raw.get("record_type") != cls.record_type:
            raise RecordValidationError(f"record_type must be {cls.record_type!r}, got {raw.get('record_type')!r}")
        version = raw.get("schema_version")
        if version != RECORD_SCHEMA_VERSION:
            raise RecordValidationError(f"unsupported record schema version: {version!r}")
        data = raw.get("data")
        if not isinstance(data, dict):
            raise RecordValidationError("record data must be an object")

        record_fields = fields(cls)
        known = {item.name for item in record_fields}
        missing = [
            item.name
            for item in record_fields
            if item.name not in data and item.default is MISSING and item.default_factory is MISSING
        ]
        if missing:
            raise RecordValidationError(f"missing record fields: {', '.join(sorted(missing))}")
        values = {item.name: data[item.name] for item in record_fields if item.name in known and item.name in data}
        return cls(**cls._coerce_values(values))


@dataclass(frozen=True, slots=True)
class SessionIdentity(_ProtocolRecord):
    """Identify one session without conflating terminal or process ownership.

    TS mirror: ``packages/protocol-ts/src/records.ts`` SessionIdentity —
    field names and nullability (terminal/process may be empty until the
    host injects them) must stay in sync across languages.
    """

    record_type: ClassVar[str] = "session_identity"

    session_id: str
    terminal_id: str
    process_id: str
    user_id: str = ""
    role: str = ""
    cell_id: str = ""
    memory_scope: str = ""

    def _validate(self) -> None:
        """Validate session identity fields."""
        _require_text(self.session_id, "session_id")
        # terminal/process ownership is host-injected and legitimately absent
        # for stdio/web sessions, so those fields are optional like the rest.
        for name in ("terminal_id", "process_id", "user_id", "role", "cell_id", "memory_scope"):
            _require_text(getattr(self, name), name, allow_empty=True)


@dataclass(frozen=True, slots=True)
class EventEnvelope(_ProtocolRecord):
    """Carry one ordered event and its optional input correlation."""

    record_type: ClassVar[str] = "event_envelope"

    event_id: str
    session_id: str
    seq: int
    event_type: str
    payload: dict[str, Any]
    input_seq: int | None = None
    trace_id: str = ""
    ts: float = field(default_factory=time.time)

    def _validate(self) -> None:
        """Validate event envelope fields."""
        _require_text(self.event_id, "event_id")
        _require_text(self.session_id, "session_id")
        _require_integer(self.seq, "seq")
        _require_text(self.event_type, "event_type")
        _require_mapping(self.payload, "payload")
        if self.input_seq is not None:
            _require_integer(self.input_seq, "input_seq", minimum=1)
        _require_text(self.trace_id, "trace_id", allow_empty=True)
        _require_timestamp(self.ts)


@dataclass(frozen=True, slots=True)
class SessionMessage(_ProtocolRecord):
    """Represent one public conversation message linked to an input."""

    record_type: ClassVar[str] = "session_message"

    message_id: str
    session_id: str
    input_seq: int
    role: str
    content: str
    trace_id: str = ""
    ts: float = field(default_factory=time.time)

    def _validate(self) -> None:
        """Validate session message fields without exposing private reasoning."""
        _require_text(self.message_id, "message_id")
        _require_text(self.session_id, "session_id")
        _require_integer(self.input_seq, "input_seq", minimum=1)
        _require_text(self.role, "role")
        _require_text(self.content, "content", allow_empty=True)
        _require_text(self.trace_id, "trace_id", allow_empty=True)
        _require_timestamp(self.ts)


@dataclass(frozen=True, slots=True)
class ToolFailure(_ProtocolRecord):
    """Describe a tool failure while preserving retry and trace context."""

    record_type: ClassVar[str] = "tool_failure"

    failure_id: str
    session_id: str
    input_seq: int
    tool_name: str
    error_kind: str
    message: str
    retryable: bool
    trace_id: str = ""
    ts: float = field(default_factory=time.time)

    def _validate(self) -> None:
        """Validate tool failure fields."""
        _require_text(self.failure_id, "failure_id")
        _require_text(self.session_id, "session_id")
        _require_integer(self.input_seq, "input_seq", minimum=1)
        _require_text(self.tool_name, "tool_name")
        _require_text(self.error_kind, "error_kind")
        _require_text(self.message, "message", allow_empty=True)
        if not isinstance(self.retryable, bool):
            raise RecordValidationError("retryable must be a boolean")
        _require_text(self.trace_id, "trace_id", allow_empty=True)
        _require_timestamp(self.ts)


@dataclass(frozen=True, slots=True)
class DecisionSummary(_ProtocolRecord):
    """Expose a concise decision result without carrying chain-of-thought."""

    record_type: ClassVar[str] = "decision_summary"

    decision_id: str
    session_id: str
    input_seq: int
    summary: str
    outcome: str
    evidence_refs: tuple[str, ...] = ()
    trace_id: str = ""
    ts: float = field(default_factory=time.time)

    @classmethod
    def _coerce_values(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Normalize JSON arrays to the immutable in-memory representation."""
        normalized = dict(values)
        if "evidence_refs" in normalized:
            normalized["evidence_refs"] = tuple(normalized["evidence_refs"])
        return normalized

    def _validate(self) -> None:
        """Validate decision summary fields and evidence identifiers."""
        _require_text(self.decision_id, "decision_id")
        _require_text(self.session_id, "session_id")
        _require_integer(self.input_seq, "input_seq", minimum=1)
        _require_text(self.summary, "summary", allow_empty=True)
        _require_text(self.outcome, "outcome")
        if not isinstance(self.evidence_refs, (tuple, list)) or any(
            not isinstance(ref, str) or not ref for ref in self.evidence_refs
        ):
            raise RecordValidationError("evidence_refs must be a string array")
        _require_text(self.trace_id, "trace_id", allow_empty=True)
        _require_timestamp(self.ts)


@dataclass(frozen=True, slots=True)
class EvidenceRef(_ProtocolRecord):
    """Point to auditable evidence without embedding private reasoning."""

    record_type: ClassVar[str] = "evidence_ref"

    evidence_id: str
    session_id: str
    input_seq: int
    kind: str
    locator: str
    digest: str = ""
    trace_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def _validate(self) -> None:
        """Validate evidence reference fields."""
        _require_text(self.evidence_id, "evidence_id")
        _require_text(self.session_id, "session_id")
        _require_integer(self.input_seq, "input_seq", minimum=1)
        _require_text(self.kind, "kind")
        _require_text(self.locator, "locator")
        _require_text(self.digest, "digest", allow_empty=True)
        _require_text(self.trace_id, "trace_id", allow_empty=True)
        _require_mapping(self.metadata, "metadata")


Record: TypeAlias = SessionIdentity | EventEnvelope | SessionMessage | ToolFailure | DecisionSummary | EvidenceRef

RECORD_TYPES: frozenset[str] = frozenset(
    {
        SessionIdentity.record_type,
        EventEnvelope.record_type,
        SessionMessage.record_type,
        ToolFailure.record_type,
        DecisionSummary.record_type,
        EvidenceRef.record_type,
    }
)
_RECORD_CLASSES: dict[str, type[_ProtocolRecord]] = {
    SessionIdentity.record_type: SessionIdentity,
    EventEnvelope.record_type: EventEnvelope,
    SessionMessage.record_type: SessionMessage,
    ToolFailure.record_type: ToolFailure,
    DecisionSummary.record_type: DecisionSummary,
    EvidenceRef.record_type: EvidenceRef,
}


def _json_value(value: Any) -> Any:
    """Convert tuples and nested mappings into JSON-compatible values."""
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def encode_record(record: Record) -> str:
    """Serialize a record to canonical JSON with stable key ordering."""
    if not isinstance(record, tuple(_RECORD_CLASSES.values())):
        raise RecordValidationError(f"unsupported record object: {type(record).__name__}")
    return json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def decode_record(line: str) -> Record:
    """Decode one canonical JSON record and reject malformed versions."""
    if not isinstance(line, str) or not line.strip():
        raise RecordValidationError("record line must be non-empty text")
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        raise RecordValidationError(f"invalid record json: {exc}") from exc
    if not isinstance(raw, dict):
        raise RecordValidationError("record must be an object")
    record_type = raw.get("record_type")
    if not isinstance(record_type, str):
        raise RecordValidationError(f"unknown record_type: {record_type!r}")
    record_cls = _RECORD_CLASSES.get(record_type)
    if record_cls is None:
        raise RecordValidationError(f"unknown record_type: {record_type!r}")
    return cast(Record, record_cls.from_dict(raw))


__all__ = [
    "RECORD_SCHEMA_VERSION",
    "RECORD_TYPES",
    "DecisionSummary",
    "EventEnvelope",
    "EvidenceRef",
    "Record",
    "RecordValidationError",
    "SessionIdentity",
    "SessionMessage",
    "ToolFailure",
    "decode_record",
    "encode_record",
]
