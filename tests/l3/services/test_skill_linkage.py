"""B5 tests — three-table linkage (TODO × card × skill) via bump_usage_for_tools."""

from __future__ import annotations

import pytest

from l1.kernel.skill import get_skill_manager, reset_skill_manager


@pytest.fixture(autouse=True)
def _clean_skills():
    """Fresh skill registry per test."""
    reset_skill_manager()
    sm = get_skill_manager()
    # Register a couple of test skills via the internal path (no write gate).
    sm._skills["read_file"] = {"name": "read_file", "useful_count": 0, "last_used": 0.0}
    sm._skills["write_file"] = {"name": "write_file", "useful_count": 0, "last_used": 0.0}
    yield
    reset_skill_manager()


def test_bump_usage_for_tools_bumps_matching_skills():
    """Matching skills gain a usage point; unknown names are reported."""
    sm = get_skill_manager()
    r = sm.bump_usage_for_tools(["read_file", "ghost_tool"])
    assert r["bumped"] == ["read_file"]
    assert r["missing"] == ["ghost_tool"]
    assert sm._skills["read_file"]["useful_count"] == 1


def test_bump_usage_for_tools_atomic_batch():
    """Multiple matching names bump under one lock acquisition."""
    sm = get_skill_manager()
    r = sm.bump_usage_for_tools(["read_file", "write_file"])
    assert set(r["bumped"]) == {"read_file", "write_file"}
    assert sm._skills["read_file"]["useful_count"] == 1
    assert sm._skills["write_file"]["useful_count"] == 1


def test_todowrite_linkage_present_in_agent_loop_context():
    """The AgentLoop todowrite handler wiring remains importable.

    ``_register_todowrite`` is a method of the AgentLoop context mixin (not
    a module function); its 'verified' branch now bumps the skill named
    after the task (TODO × skill linkage).
    """
    from l3.agent.agent_loop_context import AgentLoopContextMixin

    assert hasattr(AgentLoopContextMixin, "_register_todowrite")


def test_card_completion_linkage_bumps_tool_skills():
    """Card completion bumps skills named after the tools used (B4×B5)."""
    from l3.services.card_tool_stats import _on_card_completed, reset_card_tool_stats, wire_card_tool_stats
    from l3.services.counter import get_counter, reset_counter

    reset_counter()
    reset_card_tool_stats()
    wire_card_tool_stats()
    get_counter().record_tool("agent-a", "read_file", success=True, elapsed=0.5)
    _on_card_completed("card-1", "completed", {"agent_id": "agent-a"})

    sm = get_skill_manager()
    assert sm._skills["read_file"]["useful_count"] == 1
    reset_counter()
    reset_card_tool_stats()
