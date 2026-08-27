"""AgentLoop — LLM turn processing mixin.

Extracted from ``agent_loop_run.py``: ``_run_llm_turn`` executes one
``engine.tool_use`` call and processes its results (truncation
continuation, post-tool stub compression, tool-result processing,
continuation nudges, parallel read-only replay, consistency check).
Composed by AgentLoopRunMixin.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import as_completed
from typing import Any

from l1.kernel.params.agent import AGENT_LOOP_CONTEXT_TB_LIMIT, AGENT_LOOP_FUTURE_TIMEOUT, AGENT_LOOP_MAX_CONTENT
from l3.agent.prompts import get_prompt

from .session_snapshot import TRUNCATION_RESUME_NUDGE

logger = logging.getLogger(__name__)

# Max accumulated content length across truncation, correction, and nudge appends
_AGENT_LOOP_MAX_CONTENT: int = AGENT_LOOP_MAX_CONTENT  # chars (~25K tokens)


class LLMTurnMixin:
    """Single LLM tool_use turn processing — composed by AgentLoopRunMixin."""

    # Attributes provided by the composing AgentLoop (declared for mypy).
    agent_id: str
    task: str
    _user_id: str
    _context_trail: list[dict] | None
    _todo: Any
    _cadence: Any
    _parallel_executor: Any
    _process_tool_results: Callable[..., tuple[list, bool, int, bool]]

    def _run_llm_turn(
        self,
        *,
        engine: Any,
        system: str,
        wrapped_tools: list,
        read_only_tools: list,
        model_kwargs: dict,
        max_steps: int,
        ctx_window: int,
        side_times: dict[str, float],
        deadline: float,
        verifier: Any | None,
        t0: float,
    ) -> tuple[list, bool, int, bool, int, dict]:
        """Execute one LLM tool_use call and process its results.

        Handles truncation continuation, post-tool stub compression, the
        guard-mixin tool-result processing, continuation nudges, parallel
        read-only replay, and the consistency check. Returns the processed
        results and aggregate counters for the run orchestrator.
        """
        from l3.error_bus import error_boundary

        with error_boundary("LLM tool_use failed", component="services", agent_id=self.agent_id):
            result = engine.tool_use(
                prompt=self.task,
                tools=wrapped_tools,
                system=system,
                max_turns=max_steps,
                user_id=self._user_id,
                context_trail=self._context_trail,
                **model_kwargs,
            )
        side_times["llm_tools"] = float(result.get("tools_elapsed", 0) or 0)
        if not result:
            return (
                [],
                False,
                0,
                False,
                0,
                {
                    "success": False,
                    "answer": "",
                    "steps": [],
                    "error": "LLM call failed",
                    "verifier_used": False,
                    "corrections": 0,
                    "loop_stopped": False,
                },
            )

        self._context_trail = result.get("context_trail")
        # Persist context_trail to snapshot so it survives agent restart.
        # Only save when we have actual messages and an agent_id to key on.
        if self._context_trail and self._user_id:
            try:
                from .agent_persist import save_snapshot

                save_snapshot(
                    self._user_id,
                    {
                        "context_trail": self._context_trail,
                    },
                )
            except Exception as e:
                logger.warning("agent_loop: snapshot save failed: %s", e)
        turns = result.get("turns", 1)
        tool_results = result.get("tool_call_results", []) or []

        # ── Truncation continuation ──
        if result.get("finish_reason") == "length":
            try:
                cont = engine.generate(
                    prompt=TRUNCATION_RESUME_NUDGE, system=system, user_id=self._user_id, **model_kwargs
                )
                result["content"] = (result.get("content", "") + "\n" + cont.get("content", ""))[
                    :_AGENT_LOOP_MAX_CONTENT
                ]
                turns += 1
            except Exception as e:
                logger.warning("truncation continuation failed: %s", e)

        # ── Post-tool stub compression guard ──
        try:
            # Running total with early exit: the byte budget only needs to
            # know whether tb exceeds the limit, so stop stringifying once
            # the threshold is crossed (O(limit) instead of O(total)).
            tb = 0
            for tc in tool_results:
                tb += len(str(tc))
                if tb > AGENT_LOOP_CONTEXT_TB_LIMIT:
                    break
            if tb > AGENT_LOOP_CONTEXT_TB_LIMIT and ctx_window > 0:
                from l3.memory.memory import get_memory

                get_memory().stub_compact(self.agent_id)
        except Exception as e:
            logger.warning("agent_loop context injection failed: %s", e)

        # ── Process each tool result with loop detection + retry + cadence ──
        continuation_nudge: str | None = None
        processed_results, all_passed, corrections, verifier_used = self._process_tool_results(
            tool_results, result, system, engine, model_kwargs, deadline, verifier, side_times
        )

        # ── Continuation nudges ──
        if self._todo._continuation_nudge and self._todo.has_open_items() and processed_results:
            continuation_nudge = get_prompt("agent_loop.continuation_nudge", "")
        elif continuation_nudge is None and self._cadence.nudge():
            continuation_nudge = self._cadence.nudge()

        if continuation_nudge:
            _t_nudge = time.time()
            try:
                cont = engine.generate(prompt=continuation_nudge, system=system, user_id=self._user_id, **model_kwargs)
                result["content"] = (result.get("content", "") + "\n" + cont.get("content", ""))[
                    :_AGENT_LOOP_MAX_CONTENT
                ]
            except Exception as e:
                logger.warning("agent_loop continuation nudge failed: %s", e)
            finally:
                side_times["continuation"] += time.time() - _t_nudge

        # ── Parallel read-only tool execution ──
        if read_only_tools and processed_results:
            _t_pr = time.time()
            try:
                fs = {}
                for rt in read_only_tools:
                    for sr in processed_results:
                        if isinstance(sr, dict) and sr.get("name") == rt.name:
                            fs[self._parallel_executor.submit(rt.handler, sr.get("args", {}), self.agent_id)] = rt.name
                for f in as_completed(fs):
                    f.result(timeout=AGENT_LOOP_FUTURE_TIMEOUT)
            except Exception as e:
                logger.warning("parallel execution failed: %s", e)
            finally:
                side_times["parallel_read"] += time.time() - _t_pr

        # ── Consistency check ──
        if verifier is not None and len(processed_results) >= 2:
            cc = verifier.consistency_check(processed_results, self.task)
            if not cc.get("consistent"):
                logger.info("consistency issue: %s", cc.get("conflicts", []))

        return processed_results, all_passed, corrections, verifier_used, turns, result
