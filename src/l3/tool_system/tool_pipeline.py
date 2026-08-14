"""Tool pipeline — ring-gated tool execution for Cells.

Integrates with TOOL_REGISTRY at runtime via tools.execute_tool.
No direct import of tool_spec (avoids relative import issues).

Module layout (split for readability):
  tool_pipeline_steps.py — PipelineStepsMixin: preflight / run / finalize
                           stages (gating chain, execution, cleanup)
  tool_pipeline.py       — ToolPipeline: hooks, execute orchestration,
                           singleton (this facade)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from l1.kernel import get_event_bus
from l1.kernel.allocator import get_allocator
from l1.kernel.constitution import get_constitution
from l1.kernel.discovery import get_tool_config
from l1.kernel.gatechain import get_gatechain as _get_gatechain  # noqa: F401 — re-export (tests monkeypatch)
from l1.kernel.params.kernel import RING_1 as _RING_1
from l1.kernel.params.kernel import RING_NUM_MAP
from l1.kernel.params.tool import (
    TOOL_EXEC_TOKEN_BUDGET,
    TOOL_PIPELINE_RECORD_STEPS,
)
from l1.kernel.tool_chain import get_tool_chain
from l3.bus.reference_channel import get_rc as _get_rc  # noqa: F401 — re-export (tests monkeypatch)
from l3.scheduler.scheduler_rate import agent_can_access, get_rate_scheduler  # noqa: F401 — re-export

from .tool_pipeline_steps import PipelineStepsMixin  # noqa: F401 — re-export
from .tool_policy import ToolPolicy as _ToolPolicy  # noqa: F401 — re-export (tests monkeypatch)
from .tool_spec import ToolSpec as _ToolSpec

logger = logging.getLogger(__name__)


class _DiscardSteps(list):
    """A list that drops appended items — used when step tracing is off.

    Keeps the ``result["steps"]`` API shape (error paths still reference it)
    while avoiding per-phase dict accumulation on the hot path.
    """

    def append(self, item: Any) -> None:
        """No-op append — drops the item when step tracing is off."""
        pass


class ToolPipeline(PipelineStepsMixin):
    """Gated execution: clearance → constitution → alloc → lock → execute.

    Supports external hooks:
      - Post-execute hooks: called after tool execution with result
      - Tool-definition hooks: modify tool spec before execution
    """

    def __init__(self):
        self.constitution = get_constitution()
        self.allocator = get_allocator()
        self.bus = get_event_bus()
        self._rate_scheduler = get_rate_scheduler()
        self._post_execute_hooks: list[Callable] = []
        self._tool_definition_hooks: list[Callable] = []
        self._pmu: Any = None

    def set_pmu(self, pmu: Any) -> None:
        """Attach a Cell PMU for tool execution counters."""
        self._pmu = pmu

    def register_post_execute_hook(self, hook: Callable) -> None:
        """Register a hook called after every tool execution.

        Hook signature: (tool_name, agent_id, args, result) -> None
        Called after the tool has executed, before the chain completes.
        """
        if hook not in self._post_execute_hooks:
            self._post_execute_hooks.append(hook)

    def register_tool_definition_hook(self, hook: Callable) -> None:
        """Register a hook that modifies a tool spec before execution.

        Hook signature: (tool_name, spec) -> spec (possibly modified)
        Called after all gates pass, right before the tool runs.
        """
        if hook not in self._tool_definition_hooks:
            self._tool_definition_hooks.append(hook)

    def _run_post_execute_hooks(self, tool_name: str, agent_id: str, args: dict, result: dict) -> dict:
        """Run all post-execute hooks in registration order, tolerating failures."""
        for _hook in self._post_execute_hooks:
            try:
                _hook(tool_name, agent_id, args, result)
            except Exception as e:
                logger.debug("tool_pipeline: post-exec hook failed: %s", e)
        return result

    def apply_tool_definition_hooks(self, tool_name: str, spec: Any) -> Any:
        """Apply tool-definition hooks in registration order (modify spec before run)."""
        for _hook in self._tool_definition_hooks:
            try:
                spec = _hook(tool_name, spec)
            except Exception as e:
                logger.debug("tool_pipeline: tool-definition hook failed: %s", e)
        return spec

    def execute(
        self,
        tool_name: str,
        agent_id: str,
        args: dict | None = None,
        domain: str = "",
        nature: str = "",
        _registry: dict | None = None,
        _executor: Any = None,
        _parent_call_id: str = "",
    ) -> dict:
        """Execute a tool through the pipeline with hierarchical call tracking.

        Args:
            domain: card-level gate scope for GateChain enforcement.
            nature: driving card's type (card→skill linkage on failure paths).
            _registry: TOOL_REGISTRY dict (passed by caller)
            _executor: execute_tool function (passed by caller)
            _parent_call_id: parent composite tool's call_id for chain tracking
        """
        _start = time.time()
        chain = get_tool_chain()
        ring_map = RING_NUM_MAP  # single source: kernel.params.RING_NUM_MAP
        spec_raw = (_registry or {}).get(tool_name) if _registry else None
        spec = spec_raw if isinstance(spec_raw, _ToolSpec) else None
        tool_ring_str = spec.ring if spec else _RING_1
        tool_ring_num = ring_map.get(tool_ring_str, 1)

        tool_danger = spec.danger if spec else 0
        # ── Unified harness control bar ──
        # One read of the active harness level yields the process-step skip
        # table, the presentation mode, and the toolset whitelist. The bottom
        # line (constitution, gatechain, sandbox, reference-channel recording)
        # is never skipped; only process steps (approval/rate/pool) can be
        # dropped, and the open class (minimal) additionally restricts the
        # model-visible toolset.
        from l1.kernel.params.tool import (
            HARNESS_MODE_DEFAULT,
            HARNESS_MODES,
            HARNESS_PRESETS,
            TOOL_PRESENTATION_CODE,
        )
        from l3.tool_system.harness import get_harness_mode
        from l3.tool_system.tool_presentation import get_presentation_mode

        harness_mode = get_harness_mode()
        if harness_mode not in HARNESS_MODES:
            harness_mode = HARNESS_MODE_DEFAULT
        preset = HARNESS_PRESETS[harness_mode]
        _skip = set(preset["steps"])  # type: ignore[arg-type]
        _toolset: tuple[str, ...] | None = preset["toolset"]  # type: ignore[assignment]
        _presentation: str = preset["presentation"]  # type: ignore[assignment]

        # Code Mode / PTC (tools:code-only): under ``code`` presentation (from
        # the harness preset or an explicit runtime switch) the model may call
        # ONLY the reserved run_code transport directly; any other tool name
        # resolves to UNKNOWN_TOOL before the gating chain runs.
        code_only = _presentation == TOOL_PRESENTATION_CODE or get_presentation_mode() == TOOL_PRESENTATION_CODE
        if code_only and tool_name != "run_code":
            return {
                "success": False,
                "error": f"UNKNOWN_TOOL: {tool_name} is not exposed under code presentation (tools:code-only)",
                "tool": tool_name,
                "agent": agent_id,
            }
        # Open-class toolset whitelist (e.g. minimal = bash + string editor):
        # tools outside the whitelist are not model-visible at this level.
        if _toolset is not None and tool_name not in _toolset:
            return {
                "success": False,
                "error": f"UNKNOWN_TOOL: {tool_name} is not exposed at harness level {harness_mode}",
                "tool": tool_name,
                "agent": agent_id,
            }
        call_id = chain.start(tool_name, agent_id, ring=tool_ring_num, parent_id=_parent_call_id)
        # Step tracing toggle — off skips per-phase gate traces on the hot path.
        record_steps = bool(get_tool_config("record_steps", TOOL_PIPELINE_RECORD_STEPS))
        # Token budget read once per execution (used across alloc/free paths).
        token_budget = get_tool_config("exec_token_budget", TOOL_EXEC_TOKEN_BUDGET)
        result: dict[str, Any] = {
            "tool": tool_name,
            "agent": agent_id,
            "ring": tool_ring_str,
            "danger": tool_danger,
            "steps": [] if record_steps else _DiscardSteps(),
            "call_id": call_id,
            "harness_mode": harness_mode,
        }

        # ── Gating chain (validate → clearance → approval → rate → constitution → gatechain → sandbox) ──
        blocked = self._preflight_checks(
            tool_name=tool_name,
            agent_id=agent_id,
            args=args or {},
            domain=domain,
            nature=nature,
            _registry=_registry,
            _executor=_executor,
            _parent_call_id=_parent_call_id,
            result=result,
            spec=spec,
            tool_ring_str=tool_ring_str,
            token_budget=token_budget,
            _skip=_skip,
            _start=_start,
            call_id=call_id,
        )
        if blocked is not None:
            return blocked

        # ── Execution (alloc → pool → lock → run → failure tracking → release) ──
        fpath = (args or {}).get("path", "")
        blocked = self._run_tool(
            tool_name=tool_name,
            agent_id=agent_id,
            args=args or {},
            domain=domain,
            nature=nature,
            _registry=_registry,
            _executor=_executor,
            result=result,
            spec=spec,
            tool_ring_str=tool_ring_str,
            token_budget=token_budget,
            _skip=_skip,
            fpath=fpath,
            call_id=call_id,
        )
        if blocked is not None:
            return blocked

        # ── Finalize (post-execute hooks → chain complete → signal) ──
        return self._finalize(
            tool_name=tool_name,
            agent_id=agent_id,
            args=args or {},
            result=result,
            call_id=call_id,
            _parent_call_id=_parent_call_id,
            _start=_start,
        )


_pipeline: ToolPipeline | None = None


def get_pipeline() -> ToolPipeline:
    """Get the tool pipeline singleton."""
    global _pipeline
    if _pipeline is None:
        _pipeline = ToolPipeline()
    return _pipeline


def reset_pipeline() -> None:
    """Reset the tool pipeline singleton to None."""
    global _pipeline
    _pipeline = None
