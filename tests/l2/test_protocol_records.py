"""Contract-pin tests for the versioned TS-neutral protocol records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from l2.protocol import (
    RECORD_DATA_SCHEMAS,
    RECORD_ENVELOPE_JSON_SCHEMA,
    RECORD_SCHEMA_VERSION,
    RECORD_TYPES,
    DecisionSummary,
    EventEnvelope,
    EvidenceRef,
    RecordValidationError,
    SessionIdentity,
    SessionMessage,
    ToolFailure,
    decode_record,
    encode_record,
)


def _records() -> list[object]:
    """Return representative records for round-trip contract tests."""
    return [
        SessionIdentity(
            session_id="s-1",
            terminal_id="terminal-1",
            process_id="process-1",
            user_id="u-1",
            role="operator",
            cell_id="cell-a",
            memory_scope="user:u-1",
        ),
        EventEnvelope(
            event_id="event-1",
            session_id="s-1",
            seq=2,
            event_type="tool.completed",
            payload={"success": True, "labels": ["stable", "json"]},
            input_seq=1,
            trace_id="trace-1",
            ts=100,
        ),
        SessionMessage(
            message_id="message-1",
            session_id="s-1",
            input_seq=1,
            role="assistant",
            content="The result is ready.",
            trace_id="trace-1",
            ts=101,
        ),
        ToolFailure(
            failure_id="failure-1",
            session_id="s-1",
            input_seq=1,
            tool_name="read_file",
            error_kind="timeout",
            message="tool timed out",
            retryable=True,
            trace_id="trace-1",
            ts=102,
        ),
        DecisionSummary(
            decision_id="decision-1",
            session_id="s-1",
            input_seq=1,
            summary="The requested file was inspected.",
            outcome="completed",
            evidence_refs=("evidence-1",),
            trace_id="trace-1",
            ts=103,
        ),
        EvidenceRef(
            evidence_id="evidence-1",
            session_id="s-1",
            input_seq=1,
            kind="tool_result",
            locator="tool:read_file:call-1",
            digest="sha256:abc",
            trace_id="trace-1",
            metadata={"source": "tool_pipeline"},
        ),
    ]


def _fixture_records() -> list[dict[str, object]]:
    """Load the language-neutral JSON fixture shared with the future TS tests."""
    fixture = Path(__file__).parents[1] / "fixtures" / "protocol_v1_records.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


class TestRecordRoundTrip:
    """Canonical serialization and decoding behavior."""

    @pytest.mark.parametrize("record", _records())
    def test_round_trip_preserves_record(self, record: object) -> None:
        """Each record survives canonical JSON serialization."""
        line = encode_record(record)  # type: ignore[arg-type]
        decoded = decode_record(line)
        assert decoded.to_dict() == record.to_dict()  # type: ignore[attr-defined]
        assert json.loads(line) == record.to_dict()  # type: ignore[attr-defined]

    def test_encoding_is_deterministic_and_unicode_safe(self) -> None:
        """Key ordering and UTF-8 content are stable across repeated encodes."""
        record = SessionMessage("m-1", "s-1", 1, "user", "你好", ts=0.0)
        assert encode_record(record) == encode_record(record)
        assert "你好" in encode_record(record)

    def test_shared_fixture_decodes(self) -> None:
        """The checked-in fixture is a valid cross-language contract sample."""
        for raw in _fixture_records():
            decoded = decode_record(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            assert decoded.to_dict() == raw


class TestRecordCompatibility:
    """Version and unknown-field compatibility rules."""

    def test_unknown_fields_are_ignored(self) -> None:
        """Future fields do not prevent an older reader from accepting a record."""
        raw = SessionIdentity("s-1", "terminal-1", "process-1").to_dict()
        raw["future_field"] = {"enabled": True}
        raw["data"]["future_context"] = "ignored"
        decoded = SessionIdentity.from_dict(raw)
        assert decoded == SessionIdentity("s-1", "terminal-1", "process-1")

    def test_decoded_evidence_refs_are_immutable(self) -> None:
        """Decoded decision summaries retain their tuple representation."""
        record = next(record for record in _records() if isinstance(record, DecisionSummary))
        decoded = decode_record(encode_record(record))
        assert isinstance(decoded, DecisionSummary)
        assert decoded.evidence_refs == ("evidence-1",)

    def test_unsupported_version_is_rejected(self) -> None:
        """A reader never silently interprets a newer record schema."""
        raw = SessionIdentity("s-1", "terminal-1", "process-1").to_dict()
        raw["schema_version"] = RECORD_SCHEMA_VERSION + 1
        with pytest.raises(RecordValidationError, match="unsupported record schema version"):
            decode_record(json.dumps(raw))

    def test_unknown_record_type_is_rejected(self) -> None:
        """Unknown record kinds fail closed instead of becoming generic data."""
        with pytest.raises(RecordValidationError, match="unknown record_type"):
            decode_record(json.dumps({"record_type": "future", "schema_version": 1, "data": {}}))

    def test_missing_required_field_is_rejected(self) -> None:
        """Required identity fields cannot be omitted by a compatibility reader."""
        raw = SessionIdentity("s-1", "terminal-1", "process-1").to_dict()
        del raw["data"]["process_id"]
        with pytest.raises(RecordValidationError, match="missing record fields"):
            SessionIdentity.from_dict(raw)


class TestRecordSchema:
    """Machine-readable schemas remain aligned with the record vocabulary."""

    def test_schema_lists_all_record_types(self) -> None:
        """The envelope schema and data schema registry have the same kinds."""
        assert set(RECORD_DATA_SCHEMAS) == RECORD_TYPES
        assert set(RECORD_ENVELOPE_JSON_SCHEMA["properties"]["record_type"]["enum"]) == RECORD_TYPES
        assert RECORD_ENVELOPE_JSON_SCHEMA["properties"]["schema_version"]["const"] == RECORD_SCHEMA_VERSION

    def test_schema_required_fields_cover_records(self) -> None:
        """Required schema fields are present in every representative record."""
        for record in _records():
            schema = RECORD_DATA_SCHEMAS[record.record_type]  # type: ignore[attr-defined]
            assert set(schema["required"]).issubset(record.to_dict()["data"])  # type: ignore[attr-defined]
