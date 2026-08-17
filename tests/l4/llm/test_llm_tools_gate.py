"""llm_tools — ungated spec handler rejection (W1.3)."""

from __future__ import annotations

from l3.tool_system.tool_spec import ToolSpec
from l4.llm.llm_tools import LLMToolsMixin


def _spec(gated: bool) -> ToolSpec:
    """Build a ToolSpec with the given gated flag."""
    return ToolSpec(
        name="t",
        description="d",
        category="c",
        ring="RING_1",
        danger=1,
        handler=lambda args, agent_id="": {"success": True},
        gated=gated,
    )


def test_ungated_spec_rejected() -> None:
    """Direct handler execution is rejected unless the spec is pipeline-wrapped."""
    r = LLMToolsMixin._execute_one_tool(_spec(gated=False), {}, "c1", "t")
    assert r.get("error", "").startswith("UNGATED_TOOL")


def test_gated_spec_runs() -> None:
    """Pipeline-wrapped specs may still execute through the engine."""
    r = LLMToolsMixin._execute_one_tool(_spec(gated=True), {}, "c1", "t")
    assert r.get("result") == {"success": True}
