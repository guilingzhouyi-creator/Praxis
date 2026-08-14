"""B3 tests — TodoTracker register-backed snapshot + per-agent query."""

from __future__ import annotations

import pytest

from l1.kernel.registry import get_registry
from l3.services.todo_tracker import TodoTracker


@pytest.fixture(autouse=True)
def _clean_registry_section():
    """Drop the todo_table section before and after each test."""
    reg = get_registry()
    reg.clear_section("todo_table")
    yield
    reg.clear_section("todo_table")


def _tracker(tmp_path, state: str = "") -> TodoTracker:
    """Build an isolated tracker writing to a temp state file."""
    path = state or str(tmp_path / "todo_state.json")
    return TodoTracker(state_path=path)


def test_persist_writes_register_snapshot(tmp_path):
    """_persist() mirrors the TODO table into the L1 registry section."""
    tr = _tracker(tmp_path)
    tr.load([{"content": "task one", "status": "pending"}])
    tr.update("task one", "in_progress")
    snapshot = get_registry().todo_table()
    assert snapshot["status"] == "open"
    tasks = snapshot["tasks"]
    assert any(t["content"] == "task one" and t["status"] == "in_progress" for t in tasks)


def test_register_snapshot_readable_without_state_file():
    """The registry section is readable even when the state file is absent."""
    snapshot = get_registry().todo_table()
    assert snapshot == {"status": "open", "iteration": 0, "tasks": []}


def test_list_for_agent_scoping(tmp_path):
    """list_for_agent filters by the item's agent_id field."""
    tr = _tracker(tmp_path)
    tr.load(
        [
            {"content": "scoped task", "status": "pending", "agent_id": "cell-1:agent-a"},
            {"content": "unscoped task", "status": "pending"},
        ]
    )
    assert [t["content"] for t in tr.list_for_agent("cell-1:agent-a")] == ["scoped task"]
    # Unscoped tasks surface for the empty agent id only.
    assert [t["content"] for t in tr.list_for_agent("")] == ["unscoped task"]
    assert tr.list_for_agent("cell-1:agent-b") == []


def test_agent_loop_todowrite_linkage_updates_snapshot(tmp_path):
    """The AgentLoop todowrite path (update→persist) refreshes the snapshot."""
    tr = _tracker(tmp_path)
    tr.load([{"content": "linkage task", "status": "pending"}])
    tr.update("linkage task", "verified")
    snapshot = get_registry().todo_table()
    assert any(t["content"] == "linkage task" and t["status"] == "verified" for t in snapshot["tasks"])
