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


def test_register_executor_keeps_multiple_same_identity_loops_separate():
    """Shared agent identities receive distinct executor rows in the TODO register."""
    reset_todo_register()
    try:
        reg = get_todo_register()
        first = _tracker()
        second = _tracker()
        key1 = reg.register_executor("agent-shared", first)
        key2 = reg.register_executor("agent-shared", second)
        assert key1 == "agent-shared"
        assert key2 == "agent-shared#2"
        assert sorted(reg.snapshot()) == ["agent-shared", "agent-shared#2"]
    finally:
        reset_todo_register()


def test_card_binding_publishes_card_index(tmp_path):
    """Changing a tracker card immediately updates the L1 register card index."""
    from l1.kernel.registry import get_registry

    tracker = TodoTracker(state_path=str(tmp_path / "todo.json"), executor_id="exec-card")
    tracker.bind_context(card_id="card-42", session_id="session-42")
    table = get_registry().todo_table()
    assert table["cards"]["card-42"] == ["exec-card"]
    assert table["executors"]["exec-card"]["session_id"] == "session-42"


def test_unregister_removes_card_and_skill_indexes(tmp_path):
    """Removing an executor cannot leave stale card or skill rows behind."""
    from l1.kernel.registry import get_registry

    reset_todo_register()
    tracker = TodoTracker(state_path=str(tmp_path / "todo.json"), executor_id="exec-index")
    tracker.bind_context(card_id="card-9", session_id="session-9")
    tracker.update("[skill:quest-x:a] do A", "add")
    register = get_todo_register()
    register.register_executor("exec-index", tracker)
    tracker._persist()
    assert get_registry().todo_table()["skills"]["quest-x"] == ["exec-index"]
    assert register.unregister("exec-index") is True
    table = get_registry().todo_table()
    assert table["executors"] == {}
    assert table["cards"] == {}
    assert table["skills"] == {}


def test_load_normalizes_foreign_keys(tmp_path):
    """Loaded TODO items retain executor/card/session and stage links."""
    tracker = TodoTracker(
        state_path=str(tmp_path / "todo.json"), executor_id="exec-load", card_id="card-load", session_id="session-load"
    )
    tracker.load([{"content": "[skill:quest-y:b] do B"}])
    item = tracker._items[0]
    assert item["executor_id"] == "exec-load"
    assert item["card_id"] == "card-load"
    assert item["session_id"] == "session-load"
    assert item["skill_id"] == "quest-y"
    assert item["stage_id"] == "b"
