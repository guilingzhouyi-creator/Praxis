"""Tests for the session-JSON supply pipeline (P0-①)."""

from __future__ import annotations

from l3.cell.peers.l3a.session_json import append_thought, record_failed_tool, reset_sequences
from l3.memory.r4_skill_supply import (
    load_thought_lessons,
    load_tool_failure_cases,
    reset_supply_cache,
)


def test_load_tool_failure_cases_from_session_json(tmp_path, monkeypatch):
    """P0-①: *_tools.json failures become distill-ready cases."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path))
    reset_sequences()
    reset_supply_cache()
    try:
        record_failed_tool("sess-1", turn=1, tool_name="read_file", error="permission denied")
        cases = load_tool_failure_cases()
        assert len(cases) >= 1
        c = cases[0]
        assert c["tool"] == "read_file"
        assert "permission denied" in c["knowledge"]["error"]
        assert c["knowledge"]["source"] == "session_tool_failures"
    finally:
        reset_supply_cache()
        reset_sequences()


def test_load_thought_lessons_from_session_json(tmp_path, monkeypatch):
    """P0-①: *_thoughts.json chains become lesson candidates."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path))
    reset_sequences()
    reset_supply_cache()
    try:
        append_thought("sess-1", turn=1, input_seq=1, reasoning_text="step through the diff")
        lessons = load_thought_lessons()
        assert len(lessons) >= 1
        lesson = lessons[0]
        assert lesson["tool"] == "thought"
        assert "step through the diff" in lesson["knowledge"]["lesson"]
        assert lesson["knowledge"]["source"] == "session_thoughts"
    finally:
        reset_supply_cache()
        reset_sequences()


def test_supply_cache_limits(tmp_path, monkeypatch):
    """P0-①: limit caps the returned aggregate."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path))
    reset_sequences()
    reset_supply_cache()
    try:
        record_failed_tool("sess-1", turn=1, tool_name="a", error="e1")
        record_failed_tool("sess-1", turn=2, tool_name="b", error="e2")
        cases = load_tool_failure_cases(limit=1)
        assert len(cases) == 1
    finally:
        reset_supply_cache()
        reset_sequences()


def test_supply_layer_marks(tmp_path, monkeypatch):
    """P0-②: tool failures are exec-layer, thought lessons decision-layer."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path))
    reset_sequences()
    reset_supply_cache()
    try:
        record_failed_tool("sess-1", turn=1, tool_name="read_file", error="denied")
        append_thought("sess-1", turn=1, input_seq=1, reasoning_text="think")
        cases = load_tool_failure_cases()
        lessons = load_thought_lessons()
        assert cases and cases[0]["layer"] == "exec"
        assert lessons and lessons[0]["layer"] == "decision"
    finally:
        reset_supply_cache()
        reset_sequences()


def test_list_skills_layer_filter():
    """P0-②: list_skills(layer=...) filters via the layered index."""
    from l1.kernel.skill import get_skill_manager, reset_skill_manager

    reset_skill_manager()
    try:
        sm = get_skill_manager()
        sm.create("s-exec-1", description="d1", prompt="p1", layer="exec", internal=True)
        sm.create("s-dec-1", description="d2", prompt="p2", layer="decision", internal=True)
        exec_names = [s["name"] for s in sm.list_skills(layer="exec")]
        dec_names = [s["name"] for s in sm.list_skills(layer="decision")]
        assert "s-exec-1" in exec_names
        assert "s-dec-1" not in exec_names
        assert "s-dec-1" in dec_names
    finally:
        reset_skill_manager()


def test_dir_mtime_ttl_throttle(tmp_path, monkeypatch):
    """P0-①: the mtime probe is TTL-throttled (zero re-stats on hit)."""
    from l3.memory import r4_skill_supply as sup

    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path))
    reset_sequences()
    reset_supply_cache()
    try:
        record_failed_tool("sess-1", turn=1, tool_name="read_file", error="denied")
        # First probe performs the sweep and caches the result.
        first = sup._dir_mtime()
        assert first > 0
        # Second probe within TTL returns the cached value without re-sweep.
        second = sup._dir_mtime()
        assert second == first
        # The cache metadata is populated.
        assert sup._mtime_cache[0] == first
    finally:
        reset_supply_cache()
        reset_sequences()


def test_dir_mtime_reset_clears_probe(tmp_path, monkeypatch):
    """P0-①: reset_supply_cache clears the throttled probe too."""
    from l3.memory import r4_skill_supply as sup

    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path))
    reset_sequences()
    reset_supply_cache()
    try:
        record_failed_tool("sess-1", turn=1, tool_name="read_file", error="denied")
        sup._dir_mtime()
        assert sup._mtime_cache[1] > 0
        reset_supply_cache()
        assert sup._mtime_cache == (0.0, 0.0)
    finally:
        reset_supply_cache()
        reset_sequences()
