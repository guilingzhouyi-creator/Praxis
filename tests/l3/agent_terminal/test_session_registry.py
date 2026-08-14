"""Tests for the session/process dual-identity registry (3.3, P0-①)."""

from __future__ import annotations

import os

from l3.agent_terminal import (
    AgentTerminal,
    get_session,
    list_sessions,
    register_session,
    reset_sessions,
    unregister_session,
)


def test_terminal_has_process_id():
    """Every terminal pins the backing OS process id (dual identity)."""
    t = AgentTerminal("agent-pid", cell_id="cell-9")
    assert t.process_id == os.getpid()
    assert t.session_id == ""


def test_register_session_binds_dual_identity():
    reset_sessions()
    try:
        r = register_session("sess-1", "agent-a")
        assert r["success"] is True
        assert r["session_id"] == "sess-1"
        assert r["process_id"] == os.getpid()
        assert r["agent_id"] == "agent-a"
        rec = get_session("sess-1")
        assert rec["success"] is True
        assert rec["process_id"] == os.getpid()
    finally:
        reset_sessions()


def test_register_duplicate_rejected():
    reset_sessions()
    try:
        register_session("sess-1", "agent-a")
        r2 = register_session("sess-1", "agent-b")
        assert r2["success"] is False
    finally:
        reset_sessions()


def test_list_and_unregister():
    reset_sessions()
    try:
        register_session("sess-1", "agent-a")
        register_session("sess-2", "agent-b")
        lst = list_sessions()
        assert lst["success"] is True
        assert len(lst["sessions"]) == 2
        assert unregister_session("sess-1") is True
        assert len(list_sessions()["sessions"]) == 1
    finally:
        reset_sessions()


def test_session_monitor_reports_state():
    """P0-②: session_monitor aggregates per-session running status."""
    from l3.agent_terminal import reset_session_monitor, session_monitor, set_session_monitor

    reset_sessions()
    reset_session_monitor()
    try:
        set_session_monitor(enabled=True)
        register_session("sess-1", "agent-a")
        r = session_monitor()
        assert r["success"] is True
        assert r["count"] == 1
        state = r["sessions"][0]
        assert state["session_id"] == "sess-1"
        assert state["process_id"] == os.getpid()
        assert "status" in state
        assert "running" in state
        assert "cards_processed" in state
    finally:
        reset_session_monitor()
        reset_sessions()


def test_session_monitor_disabled_returns_empty():
    from l3.agent_terminal import reset_session_monitor, session_monitor, set_session_monitor

    reset_sessions()
    reset_session_monitor()
    try:
        set_session_monitor(enabled=False)
        register_session("sess-1", "agent-a")
        r = session_monitor()
        assert r.get("disabled") is True
        assert r["count"] == 0
    finally:
        reset_session_monitor()
        reset_sessions()


def test_auto_reload_resets_session():
    """P0-③: auto_reload fully resets the session (distinct from resume)."""
    from l3.agent_terminal import auto_reload_session, reset_auto_reload

    reset_sessions()
    reset_auto_reload()
    try:
        register_session("sess-1", "agent-a")
        r = auto_reload_session("agent-a", reason="stagnation:SPINNING")
        assert r["success"] is True
        assert r["status"] == "IDLE"
        assert r["reload_count"] == 1
        assert "stagnation" in r["reason"]
        r2 = auto_reload_session("agent-a", reason="test")
        assert r2["reload_count"] == 2
    finally:
        reset_auto_reload()
        reset_sessions()


def test_on_stagnation_triggers_reload():
    """P0-③: on_stagnation wires detector results into auto-reload."""
    from l3.agent_terminal import on_stagnation, reset_auto_reload

    reset_sessions()
    reset_auto_reload()
    try:
        register_session("sess-1", "agent-a")
        clean = on_stagnation({"stagnant": False}, "agent-a")
        assert clean["reloaded"] is False
        hit = on_stagnation({"stagnant": True, "pattern": "NO_DRIFT"}, "agent-a")
        assert hit["success"] is True
        assert "NO_DRIFT" in hit["reason"]
    finally:
        reset_auto_reload()
        reset_sessions()


def test_auto_reload_disabled_noop():
    from l3.agent_terminal import auto_reload_session, reset_auto_reload, set_auto_reload

    reset_sessions()
    reset_auto_reload()
    try:
        register_session("sess-1", "agent-a")
        set_auto_reload(enabled=False)
        r = auto_reload_session("agent-a", reason="test")
        assert r["success"] is False
        assert "disabled" in r["error"]
    finally:
        reset_auto_reload()
        reset_sessions()
