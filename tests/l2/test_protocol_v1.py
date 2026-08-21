"""Protocol v1 reference tests — envelope, outbox, cursor, schema, host.

These tests pin the language-agnostic wire contract so the TypeScript
mirror (parser/dispatcher/session/bridge) can be built against identical
expectations. Pure: no L3/L4 imports, no singletons, no filesystem.
"""

from __future__ import annotations

import io
import json

from l2.protocol import (
    ENVELOPE_JSON_SCHEMA,
    KIND_ACK,
    KIND_COMMAND,
    KIND_CONTROL,
    KIND_EVENT,
    KIND_INTENT,
    KIND_RESULT,
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
from l2.protocol.host import ProtocolHost


class TestEnvelope:
    """Envelope construction, validation, encoding round-trip."""

    def test_make_message_fills_contract_fields(self) -> None:
        """A constructed message carries every required envelope field."""
        msg = make_message("s-1", 7, KIND_COMMAND, {"name": "status"})
        assert msg["v"] == PROTOCOL_VERSION
        assert msg["session_id"] == "s-1"
        assert msg["seq"] == 7
        assert isinstance(msg["ts"], float)
        assert msg["kind"] == KIND_COMMAND
        assert msg["payload"] == {"name": "status"}

    def test_validate_message_accepts_valid(self) -> None:
        """A well-formed envelope yields no violations."""
        msg = make_message("s-1", 0, KIND_INTENT, {"text": "hi"})
        assert validate_message(msg) == []

    def test_validate_message_rejects_bad_fields(self) -> None:
        """Each contract violation is reported; version/kind/seq checked."""
        errors = validate_message({"v": 2, "session_id": "", "seq": -1, "ts": 0.0, "kind": "nope", "payload": []})
        joined = " | ".join(errors)
        assert "unsupported version" in joined
        assert "non-empty string" in joined
        assert "non-negative integer" in joined
        assert "unknown kind" in joined
        assert "payload must be an object" in joined

    def test_validate_message_reports_missing(self) -> None:
        """Missing required fields are all listed."""
        errors = validate_message({"kind": KIND_EVENT})
        assert any("missing field" in e for e in errors)
        assert len(errors) >= 5

    def test_validate_message_rejects_bad_payload_and_types(self) -> None:
        """Envelope validation fails closed for typed fields and payloads."""
        msg = make_message("s-1", 0, KIND_COMMAND, {"name": "status", "args": ["--json"]})
        msg["seq"] = True
        msg["ts"] = "now"
        msg["payload"] = {"name": "status", "args": "--json"}
        errors = validate_message(msg)
        joined = " | ".join(errors)
        assert "non-negative integer" in joined
        assert "ts must be a number" in joined
        assert "string array" in joined

    def test_encode_decode_round_trip(self) -> None:
        """encode/decode preserves the message exactly (canonical JSONL)."""
        msg = make_message("s-1", 3, KIND_RESULT, {"success": True, "data": {"x": 1}}, trace_id="tr-9")
        line = encode_message(msg)
        decoded, err = decode_message(line)
        assert err is None
        assert decoded == msg

    def test_decode_rejects_bad_json(self) -> None:
        """Malformed JSON yields an error, never a partial message."""
        decoded, err = decode_message("{not json")
        assert decoded is None
        assert err is not None and "invalid json" in err

    def test_decode_rejects_non_object(self) -> None:
        """A JSON array is not a valid envelope."""
        decoded, err = decode_message("[1,2,3]")
        assert decoded is None
        assert "object" in err

    def test_kinds_are_stable(self) -> None:
        """The kind vocabulary is exactly the protocol set."""
        assert {"intent", "command", "event", "result", "stream_chunk", "control", "ack"} == KINDS


class TestOutbox:
    """Bounded replay window semantics."""

    def test_append_and_unacked(self) -> None:
        """Appended messages are replayable until acked."""
        box = Outbox()
        box.append(make_message("s", 1, KIND_RESULT, {"success": True}))
        box.append(make_message("s", 2, KIND_RESULT, {"success": True}))
        assert [m["seq"] for m in box.unacked()] == [1, 2]
        assert box.last_acked == -1

    def test_ack_advances_cursor(self) -> None:
        """Acking drops covered messages and moves the cursor."""
        box = Outbox()
        box.append(make_message("s", 1, KIND_RESULT, {"success": True}))
        box.append(make_message("s", 2, KIND_RESULT, {"success": True}))
        box.ack(1)
        assert [m["seq"] for m in box.unacked()] == [2]
        assert box.last_acked == 1

    def test_cap_evicts_oldest(self) -> None:
        """The window is bounded at OUTBOX_MAXLEN."""
        box = Outbox(maxlen=3)
        for i in range(5):
            box.append(make_message("s", i, KIND_RESULT, {"success": True}))
        assert [m["seq"] for m in box.unacked()] == [2, 3, 4]
        assert OUTBOX_MAXLEN >= 3

    def test_ack_is_non_destructive_across_views(self) -> None:
        """One view acking never erases messages another view must replay."""
        box = Outbox()
        box.append(make_message("s", 1, KIND_RESULT, {"success": True}))
        box.append(make_message("s", 2, KIND_RESULT, {"success": True}))
        box.ack(1)
        # The advancing view sees only its future; a lagging view still
        # replays the full window from its own cursor.
        assert [m["seq"] for m in box.unacked()] == [2]
        assert [m["seq"] for m in box.unacked(0)] == [1, 2]


class TestSessionCursor:
    """Per-view attachment + acknowledged position."""

    def test_attach_and_detach(self) -> None:
        """Attach binds a session id; detach clears it."""
        cur = SessionCursor(view_id="web-1")
        assert not cur.attached
        cur.attach("s-9")
        assert cur.attached and cur.session_id == "s-9"
        cur.detach()
        assert not cur.attached

    def test_ack_advances_only_this_view(self) -> None:
        """A view's ack position is independent of other views."""
        cur = SessionCursor(view_id="view-a")
        cur.ack(5)
        assert cur.last_acked == 5
        cur.ack(3)
        assert cur.last_acked == 5


class TestSchema:
    """Machine-readable contract stays aligned with the reference."""

    def test_envelope_schema_shape(self) -> None:
        """The JSON Schema names the same required fields as the code."""
        assert ENVELOPE_JSON_SCHEMA["required"] == ["v", "session_id", "seq", "ts", "kind", "payload"]
        assert ENVELOPE_JSON_SCHEMA["properties"]["kind"]["enum"] == sorted(KINDS)
        assert ENVELOPE_JSON_SCHEMA["properties"]["v"]["const"] == PROTOCOL_VERSION


class TestHost:
    """Stdio bridge over the existing engine (contract-facing smoke tests)."""

    def test_command_round_trip(self) -> None:
        """A command envelope produces a result + an ack, both valid."""
        host = ProtocolHost()
        line = encode_message(make_message("s-1", 1, KIND_COMMAND, {"name": "lang"}))
        out = host.handle(line)
        kinds = [m["kind"] for m in out]
        assert kinds == [KIND_RESULT, KIND_ACK]
        for m in out:
            assert validate_message(m) == []
        assert out[0]["payload"]["success"] is True
        assert out[1]["payload"]["ack_seq"] == 1

    def test_bad_input_fail_closed(self) -> None:
        """Malformed input yields an error result, never a crash."""
        host = ProtocolHost()
        out = host.handle("not-json")
        assert len(out) == 1
        assert out[0]["kind"] == KIND_RESULT
        assert out[0]["payload"]["success"] is False

    def test_control_attach_and_recovery(self) -> None:
        """control attach/recovery emit session events."""
        host = ProtocolHost()
        attach = encode_message(make_message("s-1", 1, KIND_CONTROL, {"op": "attach", "session_id": "s-9"}))
        out = host.handle(attach)
        assert out[0]["kind"] == KIND_EVENT
        assert out[0]["payload"]["name"] == "session.attached"
        recovery = encode_message(make_message("s-1", 2, KIND_CONTROL, {"op": "recovery", "session_id": "s-9"}))
        out = host.handle(recovery)
        assert out[0]["payload"]["name"] == "session.recovered"

    def test_host_sequences_and_replay_are_session_scoped(self) -> None:
        """Each session has independent output cursors and replay windows."""
        host = ProtocolHost()
        for session_id in ("s-1", "s-2"):
            command = encode_message(make_message(session_id, 1, KIND_COMMAND, {"name": "lang"}))
            out = host.handle(command)
            assert [message["seq"] for message in out] == [1, 2]

        recovery = encode_message(make_message("s-1", 2, KIND_CONTROL, {"op": "recovery", "last_acked": 0}))
        out = host.handle(recovery)
        replay = out[0]["payload"]["data"]["replay"]
        assert [message["session_id"] for message in replay] == ["s-1"]
        assert [message["seq"] for message in replay] == [1]

        recovery = encode_message(make_message("s-2", 2, KIND_CONTROL, {"op": "recovery", "last_acked": 1}))
        out = host.handle(recovery)
        assert out[0]["payload"]["data"]["replay"] == []

    def test_host_rejects_malformed_ack_without_crashing(self) -> None:
        """Typed payload validation turns malformed ACKs into an error result."""
        host = ProtocolHost()
        line = encode_message(make_message("s-1", 1, KIND_ACK, {"ack_seq": "bad"}))
        out = host.handle(line)
        assert len(out) == 1
        assert out[0]["kind"] == KIND_RESULT
        assert out[0]["payload"]["success"] is False

    def test_ack_advances_shared_outbox_watermark(self) -> None:
        """Acknowledging through a view trims the shared session snapshot."""
        host = ProtocolHost()
        host.attach_view("s-ack", "s-ack")
        host._emit(KIND_EVENT, {"name": "e1"}, "s-ack")
        host._emit(KIND_EVENT, {"name": "e2"}, "s-ack")
        assert len(host.session_state("s-ack")["events"]) == 2
        host.handle_message(make_message("s-ack", 1, KIND_ACK, {"ack_seq": 2, "view_id": "s-ack"}))
        # The default single-view transport acks through its session view.
        assert host.session_state("s-ack")["events"] == []

    def test_shared_watermark_tracks_lagging_view(self) -> None:
        """One view acking never erases the window a lagging view needs."""
        host = ProtocolHost()
        host._get_session("s-mx")
        host._emit(KIND_EVENT, {"name": "e1"}, "s-mx")
        host._emit(KIND_EVENT, {"name": "e2"}, "s-mx")
        host.attach_view("v-a", "s-mx")
        host.attach_view("v-b", "s-mx")
        # v-a acks both; v-b stays behind -> shared snapshot keeps both.
        host.handle_message(make_message("s-mx", 1, KIND_ACK, {"ack_seq": 2, "view_id": "v-a"}))
        assert len(host.session_state("s-mx")["events"]) == 2
        # v-b catches up -> shared watermark advances and the snapshot trims.
        host.handle_message(make_message("s-mx", 1, KIND_ACK, {"ack_seq": 2, "view_id": "v-b"}))
        assert host.session_state("s-mx")["events"] == []

    def test_shared_watermark_is_per_session(self) -> None:
        """Session A's acks never touch session B's shared watermark."""
        host = ProtocolHost()
        host._get_session("s-a")
        host._get_session("s-b")
        host.attach_view("a-1", "s-a")
        host.attach_view("b-1", "s-b")
        host._emit(KIND_EVENT, {"name": "e1"}, "s-a")
        host._emit(KIND_EVENT, {"name": "e2"}, "s-b")
        # a-1 acks past its own event; b-1 never acks — per-session isolation.
        host.handle_message(make_message("s-a", 1, KIND_ACK, {"ack_seq": 1, "view_id": "a-1"}))
        assert host.session_state("s-a")["events"] == []
        assert len(host.session_state("s-b")["events"]) == 1

    def test_detached_view_leaves_shared_watermark(self) -> None:
        """A detached view stops contributing to the shared watermark."""
        host = ProtocolHost()
        host.attach_view("v-x", "s-d")
        host._emit(KIND_EVENT, {"name": "e1"}, "s-d")
        host.detach_view("v-x")
        # No attached views left — the watermark holds, fresh views replay.
        host.handle_message(make_message("s-d", 1, KIND_ACK, {"ack_seq": 1, "view_id": "v-x"}))
        assert len(host.session_state("s-d")["events"]) == 1

    def test_dispatch_args_shortcut_matches_text_path(self) -> None:
        """dispatch(text, args=...) behaves identically to the shlex path."""
        from l2.l2_shell import dispatch as _dispatch

        text = "/lang -v"
        direct = _dispatch("/lang", args=["-v"])
        parsed = _dispatch(text)  # shlex.split path
        assert direct == parsed

    def test_run_reads_jsonl_stream(self) -> None:
        """run() consumes stdin lines and writes JSONL responses."""
        host = ProtocolHost()
        stdin = io.StringIO(encode_message(make_message("s-1", 1, KIND_COMMAND, {"name": "lang"})) + "\n")
        stdout = io.StringIO()
        count = host.run(stdin, stdout)
        assert count == 1
        lines = [line for line in stdout.getvalue().strip().split("\n") if line]
        assert len(lines) == 2
        for line in lines:
            assert isinstance(json.loads(line), dict)

    def test_handler_stdout_captured_into_rendered(self, capsys) -> None:
        """Legacy handler prints are captured, keeping the JSONL stream clean."""
        host = ProtocolHost()
        out = host.handle_message(make_message("s-1", 1, KIND_COMMAND, {"name": "clear", "args": []}))
        result = next(env for env in out if env["kind"] == KIND_RESULT)
        assert result["payload"]["success"] is True
        # The ANSI clear rendered by the handler lands in the payload, not stdout.
        assert "\x1b[2J" in result["payload"]["rendered"]
        assert capsys.readouterr().out == ""
        # The enriched result still survives the canonical JSONL encode.
        assert encode_message(result)
