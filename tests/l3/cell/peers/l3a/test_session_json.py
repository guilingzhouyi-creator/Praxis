"""Tests for the decision-layer conversation-context JSON (3.3, P1-①) + thought chain (P1-②) + tool failures (P1-③) + history (P2-①)."""

from __future__ import annotations

from l3.cell.peers.l3a.session_json import (
    append_thought,
    append_turn,
    history_status,
    load_conversation,
    load_thoughts,
    load_tool_failures,
    next_input_seq,
    query_session_history,
    record_failed_tool,
    record_session_close,
    record_session_open,
    reset_history,
    reset_sequences,
    set_history,
)


def test_next_input_seq_monotonic():
    reset_sequences()
    try:
        assert next_input_seq("sess-1") == 1
        assert next_input_seq("sess-1") == 2
        assert next_input_seq("sess-2") == 1  # per-session counter
    finally:
        reset_sequences()


def test_append_and_load_pair(tmp_path, monkeypatch):
    """User input (upper layer) + model answer (lower layer) pair round-trip."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path))
    reset_sequences()
    try:
        r = append_turn("sess-1", 1, "hello", "hi there", user_tag="user", assistant_tag="assistant")
        assert r["success"] is True
        data = load_conversation("sess-1")
        assert data["session_id"] == "sess-1"
        entry = data["entries"][0]
        assert entry["seq"] == 1
        assert entry["user"] == {"tag": "user", "content": "hello"}
        assert entry["assistant"] == {"tag": "assistant", "content": "hi there"}
    finally:
        reset_sequences()


def test_append_replaces_same_seq_pairing(tmp_path, monkeypatch):
    """1:1 pairing — re-appending the same seq replaces the pair."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path / "replace"))
    reset_sequences()
    try:
        append_turn("sess-1", 1, "q1", "a1")
        append_turn("sess-1", 1, "q1b", "a1b")
        data = load_conversation("sess-1")
        assert len(data["entries"]) == 1
        assert data["entries"][0]["user"]["content"] == "q1b"
        assert data["entries"][0]["assistant"]["content"] == "a1b"
    finally:
        reset_sequences()


def test_load_missing_returns_empty():
    reset_sequences()
    try:
        assert load_conversation("no-such-session") == {}
    finally:
        reset_sequences()


def test_append_and_load_thought(tmp_path, monkeypatch):
    """P1-②: the thought chain lands in its SEPARATE JSON (auto-tagged)."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path / "thoughts"))
    reset_sequences()
    try:
        # Distinct session id — get_paths() caches data_dir, so tests share
        # the default dir; a unique id keeps this file self-contained.
        sid = "sess-thought"
        r = append_thought(sid, turn=1, input_seq=1, reasoning_text="think step by step")
        assert r["success"] is True
        data = load_thoughts(sid)
        assert data["session_id"] == sid
        t = data["thoughts"][0]
        assert t["turn"] == 1
        assert t["seq"] == 1
        assert t["tag"] == "thought"
        assert "step by step" in t["content"]
        # Separate file: conversation JSON for this session is untouched.
        assert load_conversation(sid) == {}
    finally:
        reset_sequences()


def test_append_thought_replaces_same_turn_seq(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path / "thoughts2"))
    reset_sequences()
    try:
        sid = "sess-thought2"
        append_thought(sid, turn=1, input_seq=1, reasoning_text="v1")
        append_thought(sid, turn=1, input_seq=1, reasoning_text="v2")
        data = load_thoughts(sid)
        assert len(data["thoughts"]) == 1
        assert data["thoughts"][0]["content"] == "v2"
    finally:
        reset_sequences()


def test_record_failed_tool(tmp_path, monkeypatch):
    """P1-③: only FAILED tool calls land in the tool-result JSON."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path / "tools"))
    reset_sequences()
    try:
        sid = "sess-tools"
        r = record_failed_tool(sid, turn=1, tool_name="read_file", error="permission denied")
        assert r["success"] is True
        data = load_tool_failures(sid)
        assert data["session_id"] == sid
        f = data["failures"][0]
        assert f["tool"] == "read_file"
        assert "permission denied" in f["error"]
        # Conversation JSON for this session is untouched (separate file).
        assert load_conversation(sid) == {}
    finally:
        reset_sequences()


def test_record_failed_tool_appends_multiple(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path / "tools2"))
    reset_sequences()
    try:
        sid = "sess-tools2"
        record_failed_tool(sid, turn=1, tool_name="a", error="e1")
        record_failed_tool(sid, turn=2, tool_name="b", error="e2")
        data = load_tool_failures(sid)
        assert len(data["failures"]) == 2
        assert data["failures"][1]["tool"] == "b"
    finally:
        reset_sequences()


def test_session_history_open_close_query(tmp_path, monkeypatch):
    """P2-①: open/close records start/end/duration; query retrieves."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path / "history"))
    reset_sequences()
    reset_history()
    try:
        sid = "sess-hist"
        assert history_status()["enabled"] is True  # default ON
        record_session_open(sid, title="demo")
        record_session_close(sid, task_summary="done")
        r = query_session_history(session_id=sid)
        assert r["success"] is True
        assert r["count"] == 1
        rec = r["sessions"][0]
        assert rec["session_id"] == sid
        assert rec["started_at"] > 0
        assert rec["ended_at"] > 0
        assert rec["duration"] >= 0
        assert rec["task_summary"] == "done"
    finally:
        reset_history()
        reset_sequences()


def test_session_history_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path / "history2"))
    reset_sequences()
    reset_history()
    try:
        set_history(enabled=False)
        assert history_status()["enabled"] is False
        r = query_session_history()
        assert r.get("disabled") is True
        assert r["count"] == 0
    finally:
        reset_history()
        reset_sequences()
