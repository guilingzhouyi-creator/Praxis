"""Tests for AgentLoop.context_snapshot — per-entity context management (isolation)."""

from __future__ import annotations

from l3.agent.agent_loop import AgentLoop, audit_cell_context, reset_loop_registry


def test_context_snapshot_reports_identity_and_empty_trail():
    loop = AgentLoop(task="test", agent_id="agent-snap", cell_id="cell-1", todo_path="")
    snap = loop.context_snapshot()
    assert snap["agent_id"] == "agent-snap"
    assert snap["cell_id"] == "cell-1"
    assert snap["trail_messages"] == 0
    assert snap["trail_tokens"] == 0
    assert snap["isolated"] is True


def test_context_snapshot_reflects_trail_and_card():
    loop = AgentLoop(task="snapshot-task", agent_id="agent-snap2", cell_id="cell-2", todo_path="")
    loop._context_trail = [
        {"role": "user", "content": "first message with enough text"},
        {"role": "assistant", "content": "reply with enough text"},
    ]
    loop.set_card_tags(["build"])
    snap = loop.context_snapshot()
    assert snap["trail_messages"] == 2
    assert snap["trail_tokens"] > 0
    assert snap["card_tags"] == ["build"]


def test_context_snapshot_isolated_per_entity():
    """Two agents' snapshots never share trail data (per-entity isolation)."""
    a = AgentLoop(task="t", agent_id="agent-iso-a", cell_id="cell-9", todo_path="")
    AgentLoop(task="t", agent_id="agent-iso-b", cell_id="cell-9", todo_path="")
    a._context_trail = [{"role": "user", "content": "only-a context data here"}]
    assert a.context_snapshot()["trail_messages"] == 1


def test_audit_cell_context_aggregates_per_agent():
    """audit_cell_context sums trail pressure per agent for a Cell."""
    reset_loop_registry()
    try:
        a = AgentLoop(task="t", agent_id="agent-aud-a", cell_id="cell-9", todo_path="")
        AgentLoop(task="t", agent_id="agent-aud-b", cell_id="cell-9", todo_path="")
        a._context_trail = [{"role": "user", "content": "context data for audit"}]
        r = audit_cell_context("cell-9")
        assert r["success"] is True
        assert r["agents"] == 2
        assert r["total_trail_messages"] == 1
        assert r["per_agent"]["agent-aud-a"]["trail_messages"] == 1
        assert r["per_agent"]["agent-aud-b"]["trail_messages"] == 0
    finally:
        reset_loop_registry()


def test_audit_cell_context_filters_by_cell():
    """audit_cell_context(cell-A) excludes loops of other Cells."""
    reset_loop_registry()
    try:
        AgentLoop(task="t", agent_id="agent-cell-a", cell_id="cell-A", todo_path="")
        AgentLoop(task="t", agent_id="agent-cell-b", cell_id="cell-B", todo_path="")
        r = audit_cell_context("cell-A")
        assert r["agents"] == 1
        assert list(r["per_agent"].keys()) == ["agent-cell-a"]
    finally:
        reset_loop_registry()
