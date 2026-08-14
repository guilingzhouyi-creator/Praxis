"""Tests for the in-memory TodoRegister (multi-AgentLoop TODO view)."""

from __future__ import annotations

import tempfile

from l3.services.todo_tracker import TodoTracker, get_todo_register, reset_todo_register


def _tracker():
    """Isolated tracker: unique state path avoids cross-test pollution."""
    return TodoTracker(state_path=tempfile.mktemp(suffix=".json"))


def test_register_and_get():
    reset_todo_register()
    try:
        reg = get_todo_register()
        tracker = _tracker()
        assert reg.register("exec-A", tracker) is True
        assert reg.get("exec-A") is tracker
        # second registration for the same executor wins first
        assert reg.register("exec-A", _tracker()) is False
    finally:
        reset_todo_register()


def test_snapshot_aggregates_executors():
    reset_todo_register()
    try:
        reg = get_todo_register()
        t1 = _tracker()
        t2 = _tracker()
        reg.register("exec-A", t1)
        reg.register("exec-B", t2)
        t1.update("task1", "pending")
        t2.update("task2", "pending")
        t2.update("task2", "in_progress")
        t2.update("task2", "verified")
        snap = reg.snapshot()
        assert sorted(snap.keys()) == ["exec-A", "exec-B"]
        assert snap["exec-A"]["total_tasks"] == 1
        assert snap["exec-B"]["by_status"].get("verified") == 1
        assert sorted(reg.snapshot("exec-B").keys()) == ["exec-B"]
    finally:
        reset_todo_register()


def test_unregister_and_clear():
    reset_todo_register()
    try:
        reg = get_todo_register()
        reg.register("exec-A", _tracker())
        reg.register("exec-B", _tracker())
        assert reg.unregister("exec-A") is True
        assert "exec-A" not in reg.snapshot()
        reg.clear()
        assert reg.snapshot() == {}
    finally:
        reset_todo_register()


def test_agentloop_registers_tracker():
    """AgentLoop construction registers its TodoTracker in the register."""
    reset_todo_register()
    try:
        from l3.agent.agent_loop import AgentLoop

        loop = AgentLoop(task="test", agent_id="agent-reg", todo_path=tempfile.mktemp(suffix=".json"))
        reg = get_todo_register()
        assert reg.get("agent-reg") is loop._todo
    finally:
        reset_todo_register()
