"""Single public tool-invocation gate (W1.2).

Every tool execution that is not an agent-loop pipeline call must enter
through ``invoke_gated`` so the full gate chain (clearance, approval, rate,
constitution, gatechain, sandbox, audit) always applies. Direct calls to the
registry-level executor (``tool_spec._execute_tool_spec``) are forbidden by
``tests/infra/test_single_execution_gate.py``.
"""

from __future__ import annotations

from typing import Any


def invoke_gated(
    tool_name: str,
    args: dict | None = None,
    agent_id: str = "",
    domain: str = "",
    nature: str = "",
    interactive: bool = False,
) -> dict:
    """Run one tool through the full tool pipeline (the only gate).

    Args:
        tool_name: registered tool name.
        args: tool arguments.
        agent_id: process-table agent id, or a boundary principal for
            interactive callers.
        domain: card-level gate scope.
        nature: driving card's type.
        interactive: True for boundary principals (local shell / API / MCP
            behind closed-by-default auth) whose identity is established
            outside the kernel process table.

    Returns:
        Pipeline result dict (success + result); never raises for gate
        rejections.
    """
    from l3.tool_system.tool_pipeline import get_pipeline
    from l3.tool_system.tool_registry import TOOL_REGISTRY

    registry: dict[str, Any] | None = TOOL_REGISTRY if TOOL_REGISTRY else None
    return get_pipeline().execute(
        tool_name=tool_name,
        agent_id=agent_id,
        args=args or {},
        domain=domain,
        nature=nature,
        _registry=registry,
        _interactive=interactive,
    )
