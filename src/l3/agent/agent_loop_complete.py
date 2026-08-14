"""AgentLoop — steps-exhausted continuation and finish funnel mixins.

Extracted from ``agent_loop_run.py``: ``_run_steps_exhausted`` (bounded
auto-continuation after the step budget is spent) and ``_finish`` (the
centralized terminal funnel — counters, cadence cleanup, cell-cache
injection, transcript append, lifecycle hooks). Composed by
AgentLoopRunMixin.
"""

from __future__ import annotations

import hashlib as _hl
import logging
import time
from collections.abc import Callable
from typing import Any

from l1.kernel.params.agent import AGENT_LOOP_MAX_CONTENT, AGENT_LOOP_UNLIMITED_STEPS
from l1.kernel.params.system import (
    HASH_TRUNC_SHORT,
    LOG_TRUNC_100,
    LOG_TRUNC_200,
    MEMORY_IMPORTANCE_DECISION,
    MEMORY_PROMOTION_THRESHOLD,
)

from .session_snapshot import STEPS_EXHAUSTED_NUDGE

logger = logging.getLogger(__name__)

# Max accumulated content length across truncation, correction, and nudge appends
_AGENT_LOOP_MAX_CONTENT: int = AGENT_LOOP_MAX_CONTENT  # chars (~25K tokens)


class StepsExhaustedMixin:
    """Steps-exhausted auto-continuation — composed by AgentLoopRunMixin."""

    # Attributes provided by the composing AgentLoop (declared for mypy).
    agent_id: str
    task: str
    _user_id: str
    _context_trail: list[dict] | None
    _finish: Callable[..., Any]

    def _run_steps_exhausted(
        self,
        *,
        engine: Any,
        system: str,
        wrapped_tools: list,
        model_kwargs: dict,
        max_steps: int,
        ctx_window: int,
        deadline: float,
        side_times: dict[str, float],
        result: dict,
        processed_results: list,
        all_passed: bool,
        corrections: int,
        verifier_used: bool,
        turns: int,
        t0: float,
    ) -> tuple[bool, int, list]:
        """Auto-continue after steps are exhausted: compress, nudge, re-run.

        Bounded by ``loop.max_attempts`` (SettingsCenter, default 3).
        Early-returns the terminal result dict (via ``_finish``) when the
        continuation nudge is disabled; otherwise mutates and returns the
        aggregate state for the run orchestrator.
        """
        if (
            not all_passed
            and max_steps < AGENT_LOOP_UNLIMITED_STEPS
            and result.get("finish_reason") in ("max_turns", "stop")
        ):
            from l3.error_bus import error_boundary

            with error_boundary("steps-exhausted continuation failed", component="agent", agent_id=self.agent_id):
                from l3.config.settings_center import get_center as _get_c

                _sc = _get_c()
                if not _sc.get("loop.continuation_nudge", True):
                    self._finish(
                        {
                            "success": all_passed,
                            "answer": result.get("content", ""),
                            "steps": [
                                {"step": i, "action": tc.get("name", "?"), "result": str(tc)[:LOG_TRUNC_200]}
                                for i, tc in enumerate(processed_results)
                            ],
                            "verifier_used": verifier_used,
                            "corrections": corrections,
                            "loop_stopped": any(
                                s.get("_loop_stopped") for s in processed_results if isinstance(s, dict)
                            ),
                        },
                        t0=t0,
                        turns=turns,
                        corrections=corrections,
                        processed_count=len(processed_results),
                    )
                    return all_passed, turns, processed_results
                _max_attempts = _sc.get_int("loop.max_attempts", 3)
                for _attempt in range(_max_attempts):
                    _t_se = time.time()
                    # 1. Compress context
                    try:
                        from .session_snapshot import should_compress as _sc2

                        if ctx_window > 0 and _sc2(_AGENT_LOOP_MAX_CONTENT, ctx_window):
                            from l3.memory.memory import get_memory

                            get_memory().stub_compact(self.agent_id)
                    except (ImportError, AttributeError):
                        logger.debug("agent_loop: steps-exhausted compress failed")
                    # 2. Save context trail snapshot
                    if self._context_trail and self._user_id:
                        try:
                            from .agent_persist import save_snapshot

                            save_snapshot(
                                self._user_id,
                                {
                                    "context_trail": self._context_trail,
                                },
                            )
                        except (ImportError, AttributeError, OSError):
                            logger.debug("agent_loop: steps-exhausted snapshot failed")
                    # 3. Issue steps-exhausted nudge + continue
                    nudge_r = engine.generate(
                        prompt=STEPS_EXHAUSTED_NUDGE, system=system, user_id=self._user_id, **model_kwargs
                    )
                    result["content"] = (result.get("content", "") + "\n" + nudge_r.get("content", ""))[
                        :_AGENT_LOOP_MAX_CONTENT
                    ]
                    # 4. Run next tool-use batch
                    nr = engine.tool_use(
                        prompt=self.task,
                        tools=wrapped_tools,
                        system=system,
                        max_turns=max_steps,
                        user_id=self._user_id,
                        context_trail=self._context_trail,
                        **model_kwargs,
                    )
                    side_times["continuation"] += time.time() - _t_se
                    if not nr:
                        break
                    self._context_trail = nr.get("context_trail")
                    nr_turns = nr.get("turns", 0)
                    turns += nr_turns
                    # Merge new tool results
                    nr_tools = nr.get("tool_call_results", [])
                    for _sr in nr_tools:
                        processed_results.append(
                            {
                                "step": len(processed_results),
                                "action": (_sr.get("name", "?") if isinstance(_sr, dict) else "?"),
                                "result": str(_sr)[:LOG_TRUNC_200],
                            }
                        )
                    # 5. Check completion
                    nr_finish = nr.get("finish_reason", "")
                    if nr_finish in ("stop", "end_turn"):
                        all_passed = True
                        break
                    if time.time() > deadline:
                        break

        return all_passed, turns, processed_results


class FinishFunnelMixin:
    """Centralized terminal funnel — composed by AgentLoopRunMixin."""

    # Attributes provided by the composing AgentLoop (declared for mypy).
    agent_id: str
    task: str
    _user_id: str
    _cell_id: str
    _todo: Any
    _cadence: Any
    _run_count: int

    def _finish(
        self, result: dict, *, t0: float, turns: int = 0, corrections: int = 0, processed_count: int = 0
    ) -> dict:
        """Centralized terminal funnel — OpenCode-style.

        Called EXACTLY ONCE by every return path in run().
        Guarantees counter recording, cadence cleanup, and logging.
        Also injects a summary into the Cell's L2 cache for cross-agent sharing.
        """
        elapsed = time.time() - t0
        try:
            from l3.services.counter import get_counter

            get_counter().record_loop(
                agent_id=self._user_id,
                turns=turns + corrections,
                steps=processed_count,
                elapsed=elapsed,
                side=result.get("side_execution"),
            )
        except Exception as e:
            logger.warning("services/agent_loop: %s", e)
        try:
            from l3.services.stats_center import MetricPoint as _Mp3
            from l3.services.stats_center import get_center as _sc3

            for _k, _v in (result.get("side_execution") or {}).items():
                if _v:
                    _sc3().ingest(
                        _Mp3(
                            name=f"agent.loop.side.{_k}",
                            value=float(_v),
                            tags={"agent": self.agent_id},
                            timestamp=time.time(),
                            metric_type="gauge",
                        )
                    )
        except Exception:
            logger.debug("agent_loop: side timing stats failed")
        side = result.get("side_execution") or {}
        if side:
            try:
                from l3.bus.monitor_bus import MonitorEvent as _ME3  # noqa: N814
                from l3.bus.monitor_bus import get_bus as _MB3

                _MB3().emit(
                    _ME3(
                        type="stats.loop.side",
                        source="agent_loop",
                        severity="info",
                        message=f"{self.agent_id} side execution: {side}",
                        agent_id=self.agent_id,
                        cell_id=self._cell_id,
                        data={"side": side, "elapsed": round(elapsed, 3)},
                    )
                )
            except Exception:
                logger.debug("agent_loop: side timing monitor emit failed")
        self._todo._persist()
        # ── AutoTestGate: background test regression on card completion ──
        # Spawned when the loop left unverified edits and async mode is on.
        # Runs after cadence state is captured but before it is reset.
        try:
            from l3.tool_system.auto_test import maybe_trigger

            _unverified = self._cadence.unverified_edits()
            _card_id = getattr(self, "_last_card_id", "") or ""
            maybe_trigger(self.agent_id, self._cell_id, self.task, _unverified, card_id=_card_id)
        except Exception as e:
            logger.debug("agent_loop: auto_test trigger failed: %s", e)
        self._cadence.reset()

        # ── Cell L2 cache injection ──
        if self._cell_id:
            try:
                from l3.cell import get_cell as _get_cell

                cell = _get_cell(self._cell_id)
                answer = result.get("answer", "")
                # Use fingerprint of full task text for key uniqueness
                task_hash = _hl.sha256(self.task.encode()).hexdigest()[:HASH_TRUNC_SHORT]
                if result.get("success") and answer:
                    summary = answer.strip()[:LOG_TRUNC_200]
                    key = f"agent:{self.agent_id}:{task_hash}:r{self._run_count}"
                    cell.cache.inject(
                        key=key,
                        value=answer,
                        summary=summary,
                        agent_id=self.agent_id,
                        entry_type="decision",
                        importance=MEMORY_PROMOTION_THRESHOLD,
                    )
                elif not result.get("success") and result.get("error"):
                    error = result["error"][:LOG_TRUNC_200]
                    key = f"fail:{self.agent_id}:{task_hash}:r{self._run_count}"
                    cell.cache.inject(
                        key=key,
                        value=result.get("error", ""),
                        summary=f"FAIL [{self.agent_id}]: {error}",
                        agent_id=self.agent_id,
                        entry_type="failure",
                        importance=MEMORY_IMPORTANCE_DECISION,
                    )
            except Exception as e:
                logger.debug("cell cache inject: %s", e)

        # ── Snapshot hook ──
        try:
            from l3.agent.agent_persist import append_transcript

            record = {
                "task": self.task[:LOG_TRUNC_100],
                "success": result.get("success", False),
                "steps": result.get("total_steps", 0),
                "elapsed": round(elapsed, 2),
                "summary": str(result.get("answer", ""))[:LOG_TRUNC_200],
            }
            append_transcript(self._user_id, record)
        except Exception as e:
            logger.debug("persist append: %s", e)

        result["total_elapsed"] = round(elapsed, 2)
        result["total_steps"] = turns + corrections

        # ── Lifecycle hook chain: turn_complete (always) + on_error (on failure) ──
        try:
            from l3.services.hook import get_hook_chain as _get_hc

            _get_hc().turn_complete(result, elapsed)
            if not result.get("success"):
                _get_hc().on_error(result.get("error", "agent loop failed"))
        except Exception as e:
            logger.debug("agent_loop: hook chain emit failed: %s", e)

        return result


# Module-level cap shared with the run orchestrator (agent_loop_run.py).
