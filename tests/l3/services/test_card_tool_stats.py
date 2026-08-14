"""B4 tests — tool usage accounting + card completion → tool stats linkage."""

from __future__ import annotations

import pytest

from l3.services.card_tool_stats import reset_card_tool_stats, wire_card_tool_stats
from l3.services.counter import get_counter


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset the counter singleton and the linkage flag per test."""
    from l3.services.counter import reset_counter

    reset_counter()
    reset_card_tool_stats()
    yield
    reset_counter()
    reset_card_tool_stats()


def test_counter_record_tool_then_summary():
    """record_tool entries surface in tool_summary (B4 accounting primitive)."""
    c = get_counter()
    c.record_tool("agent-a", "read_file", success=True, elapsed=0.5)
    c.record_tool("agent-a", "write_file", success=False, elapsed=1.0)
    summary = c.tool_summary("agent-a")
    assert summary["total"] == 2
    assert summary["by_tool"]["read_file"]["success"] == 1
    assert summary["by_tool"]["write_file"]["failure"] == 1


def test_card_completion_writes_registry_section():
    """A card completion aggregates tool stats into the registry section."""
    c = get_counter()
    c.record_tool("agent-a", "read_file", success=True, elapsed=0.5)
    wire_card_tool_stats()

    # Simulate the CardRegistry firing a completion listener.
    from l3.services.card_tool_stats import _on_card_completed

    _on_card_completed("card-1", "completed", {"agent_id": "agent-a", "cell_id": "cell-1"})

    from l1.kernel.registry import get_registry

    snapshot = get_registry().get_section("card_tool_stats")
    assert snapshot is not None
    assert snapshot["card_id"] == "card-1"
    assert snapshot["state"] == "completed"
    assert snapshot["agent_id"] == "agent-a"
    assert snapshot["total"] == 1


def test_card_completion_tolerates_missing_counter():
    """Aggregation degrades gracefully when no counter state exists."""
    wire_card_tool_stats()
    from l3.services.card_tool_stats import _on_card_completed

    _on_card_completed("card-2", "failed", {"agent_id": "agent-x"})  # must not raise
    from l1.kernel.registry import get_registry

    snapshot = get_registry().get_section("card_tool_stats")
    assert snapshot["card_id"] == "card-2"
    assert snapshot["state"] == "failed"
