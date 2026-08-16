"""Kernel capability syscall — the single execution authority (W6.1).

Every boundary tool invocation (L2 shell, API/MCP) enters through
``invoke_capability``; authorization + execution are delegated to the
executor wired at boot (the L3 ToolPipeline adapter). The kernel never
imports L3: boot calls ``register_capability_executor`` (same pattern as
the metric sink / posture provider). Unwired -> fail-closed BLOCK; every
invocation (accepted or denied) appends a kernel audit record.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Executor contract: (name, args, agent_id, domain, nature, interactive) -> dict
CapabilityExecutor = Callable[..., dict[str, Any]]

_executor: CapabilityExecutor | None = None


def register_capability_executor(fn: CapabilityExecutor) -> None:
    """Wire the execution authority (boot only; L3 pipeline adapter)."""
    global _executor
    _executor = fn


def reset_capability_executor() -> None:
    """Drop the wired executor (tests / shutdown)."""
    global _executor
    _executor = None


def has_capability_executor() -> bool:
    """True once boot wired an execution authority."""
    return _executor is not None


def invoke_capability(
    agent_id: str,
    name: str,
    args: dict[str, Any] | None = None,
    *,
    domain: str = "",
    nature: str = "",
    interactive: bool = False,
) -> dict[str, Any]:
    """Execute one tool through the single gated capability path.

    Fail-closed: with no wired executor the call is denied and audited.
    Every invocation (success or denial) appends a kernel audit record.
    """
    from l1.kernel import record_audit

    if _executor is None:
        result = {"success": False, "error": "no execution authority (fail-closed)", "capability": name}
        record_audit(
            "capability.invoke",
            agent_id,
            success=False,
            error=result["error"],
            detail=f"{name} (unwired)",
        )
        return result
    result = _executor(name, args or {}, agent_id=agent_id, domain=domain, nature=nature, interactive=interactive)
    if not isinstance(result, dict):
        result = {"success": False, "error": "capability executor returned non-dict result"}
    record_audit(
        "capability.invoke",
        agent_id,
        success=bool(result.get("success")),
        error=str(result.get("error", "")),
        detail=name,
    )
    return result
