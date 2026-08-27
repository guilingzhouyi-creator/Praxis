"""AgentLoop run mixin — the tool-calling loop, finish funnel, and continuation.

Extracted from ``agent_loop.py`` (AgentLoop) to slim the class. ``run()``
is the orchestrator: it resolves the step budget, builds/reuses the cached
context, delegates the LLM turn and the steps-exhausted auto-continuation
to private helpers, and funnels every exit through ``_finish()``.
``AgentLoop`` inherits this mixin so runtime behavior is unchanged.

Module layout (split for readability):
  agent_loop_turn.py     — LLMTurnMixin: single tool_use turn processing
  agent_loop_complete.py — StepsExhaustedMixin + FinishFunnelMixin
  agent_loop_run.py      — AgentLoopRunMixin: run orchestration (this facade)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from l1.kernel.params.agent import (
    AGENT_LOOP_DEFAULT_STEPS,
    AGENT_LOOP_DEFAULT_TIMEOUT,
    AGENT_LOOP_UNLIMITED_STEPS,
)
from l1.kernel.params.system import LOG_TRUNC_200
from l1.kernel.ports import get_port as _get_port

from .agent_loop_complete import FinishFunnelMixin, StepsExhaustedMixin  # noqa: F401 — re-export
from .agent_loop_turn import LLMTurnMixin  # noqa: F401 — re-export

logger = logging.getLogger(__name__)


class AgentLoopRunMixin(LLMTurnMixin, StepsExhaustedMixin, FinishFunnelMixin):
    """Tool-calling loop orchestration, finish funnel, and continuation paths."""

    # Host-provided attributes (declared by AgentLoop)
    _build_run_context: Any
    _cadence: Any
    _cell_id: Any
    _chat_params_hooks: Any
    _inject_extra_context: Any
    _loop_detector: Any
    _parallel_executor: Any
    _pre_send_compression_guard: Any
    _process_tool_results: Any
    _repeat_detector: Any
    _run_count: Any
    _todo: Any
    _user_id: Any
    agent_id: Any
    set_card_tags: Any
    _cached_system: str
    _cached_tools: tuple[list, list]
    _cached_model_kwargs: dict | None
    _context_trail: list[dict] | None

    def run(
        self,
        max_steps: int = 0,
        timeout: float = AGENT_LOOP_DEFAULT_TIMEOUT,
        verifier: Any | None = None,
        model_config: dict | None = None,
    ) -> dict:
        """Run the tool-calling loop.

        Args:
            max_steps: If 0 (default), queries SettingsCenter for ``loop.max_steps``.
                       If > 0, overrides SettingsCenter value.
                       If < 0 (e.g. -1), runs with no step limit (unlimited mode).
            model_config: Per-call overrides for LLM config.
                Keys: provider, model, max_tokens, temperature,
                      reasoning_effort, thinking_budget
                None = use global LLM engine config.
        """
        max_steps = self._resolve_max_steps(max_steps)
        self._max_steps = max_steps
        t0 = time.time()
        side_times: dict[str, float] = {
            "compression": 0.0,  # pre-send context guard (stub_compact/compact)
            "parallel_read": 0.0,  # read-only tools parallel re-execution
            "continuation": 0.0,  # nudges / verifier fixes / steps-exhausted
            "llm_tools": 0.0,  # tool handler wall time inside LLM engine
        }
        self._loop_detector.reset()
        self._repeat_detector.reset()
        self._cadence.reset()

        engine = _get_port("llm")
        if self._cached_system:
            # continue_run() path: reuse cached system prompt and tools.
            # The identical system string enables LLM prompt caching across calls.
            system = self._cached_system
            wrapped_tools, read_only_tools = self._cached_tools
            model_kwargs = self._cached_model_kwargs.copy() if self._cached_model_kwargs else {}
            if model_config:
                for key in ("model", "max_tokens", "temperature", "reasoning_effort", "thinking_budget"):
                    if key in model_config and model_config[key] is not None:
                        model_kwargs[key] = model_config[key]
            for hook in self._chat_params_hooks:
                try:
                    override = hook(self.task, self.agent_id, dict(model_kwargs))
                    if isinstance(override, dict):
                        model_kwargs.update(override)
                except Exception as e:
                    logger.warning("chat params hook failed: %s", e)
        else:
            # First run: build fresh, cache for subsequent calls.
            system, wrapped_tools, read_only_tools, model_kwargs = self._build_run_context(
                max_steps, model_config, engine
            )
            system = self._inject_extra_context(system)
            self._cached_system = system
            self._cached_tools = (wrapped_tools, read_only_tools)
            self._cached_model_kwargs = dict(model_kwargs)
        deadline = time.time() + timeout if timeout > 0 else float("inf")

        ctx_window, _guard_finish = self._pre_send_compression_guard(system, engine, side_times, t0)
        if _guard_finish is not None:
            return _guard_finish

        # ── Main LLM turn: tool_use call + processing + nudges ──
        processed_results, all_passed, corrections, verifier_used, turns, result = self._run_llm_turn(
            engine=engine,
            system=system,
            wrapped_tools=wrapped_tools,
            read_only_tools=read_only_tools,
            model_kwargs=model_kwargs,
            max_steps=max_steps,
            ctx_window=ctx_window,
            side_times=side_times,
            deadline=deadline,
            verifier=verifier,
            t0=t0,
        )

        # ── Steps-exhausted auto-continuation ──
        all_passed, turns, processed_results = self._run_steps_exhausted(
            engine=engine,
            system=system,
            wrapped_tools=wrapped_tools,
            model_kwargs=model_kwargs,
            max_steps=max_steps,
            ctx_window=ctx_window,
            deadline=deadline,
            side_times=side_times,
            result=result,
            processed_results=processed_results,
            all_passed=all_passed,
            corrections=corrections,
            verifier_used=verifier_used,
            turns=turns,
            t0=t0,
        )

        return self._finish(
            {
                "success": all_passed,
                "answer": result.get("content", ""),
                "steps": [
                    {"step": i, "action": tc.get("name", "?"), "result": tc.get("_preview") or str(tc)[:LOG_TRUNC_200]}
                    for i, tc in enumerate(processed_results)
                ],
                "reasoning_trail": result.get("reasoning_trail", []) or [],
                "reasoning_tokens": result.get("reasoning_tokens", 0) or 0,
                "side_execution": {k: round(v, 3) for k, v in side_times.items()},
                "verifier_used": verifier_used,
                "corrections": corrections,
                "loop_stopped": any(s.get("_loop_stopped") for s in processed_results if isinstance(s, dict)),
                "awaiting_input": any(isinstance(s, dict) and s.get("_awaiting_input") for s in processed_results),
            },
            t0=t0,
            turns=turns,
            corrections=corrections,
            processed_count=len(processed_results),
        )

    # ── Continuation / lifecycle helpers ──────────────────────────────────

    def continue_run(self, task: str, timeout: float | None = None, model_config: dict | None = None) -> dict:
        """Continue the AgentLoop with a new task, preserving the existing system prompt.

        Used by persistent AgentLoop mode (AgentTerminal._persistent_loop).
        The system prompt, tools, and constitution context are reused from
        the initial ``run()`` call.

        Note: this does NOT share LLM conversation context between calls.
        Each ``continue_run()`` issues a fresh ``engine.tool_use()`` call.
        For true conversational continuity across cards, enable memory recall
        via ``memory.build_context()`` in the system prompt.
        """
        self.task = task
        return self.run(
            max_steps=0,
            timeout=timeout or AGENT_LOOP_DEFAULT_TIMEOUT,
            model_config=model_config,
        )

    def update_card_context(self, tags: list[str] | None = None, nature: str = "") -> None:
        """Refresh card-derived context for a persistent loop between cards.

        The persistent AgentLoop is reused across cards; skill retrieval
        must re-bias when the next card has a different nature/domain.
        """
        if tags:
            self.set_card_tags(tags)
        if nature:
            self._card_nature = nature

    def _resolve_max_steps(self, max_steps: int) -> int:
        """Resolve the effective step limit: SettingsCenter >= caller override > default."""
        if max_steps == 0:
            try:
                from l3.config.settings_center import get_center

                max_steps = get_center().get("loop.max_steps", AGENT_LOOP_DEFAULT_STEPS)
            except (ImportError, KeyError):
                max_steps = AGENT_LOOP_DEFAULT_STEPS
        # 0 or negative → unlimited mode (use a large sentinel for LLM max_turns)
        if max_steps <= 0:
            max_steps = AGENT_LOOP_UNLIMITED_STEPS
        return max_steps
