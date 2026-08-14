"""AgentLoop guard mixin — pre-send compression guard + tool-result processing.

Extracted from ``agent_loop.py`` (AgentLoop) to slim the class. Both methods
are pure ``self``-driven helpers; ``AgentLoop`` inherits this mixin so the
runtime behavior is unchanged.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from l1.kernel.params.agent import AGENT_LOOP_MAX_CONTENT
from l1.kernel.params.system import (
    CONTEXT_BUILD_MAX_TOKENS,
    CONTEXT_PRESSURE_CRITICAL,
    CONTEXT_PRESSURE_MEDIUM,
    CONTEXT_PRESSURE_WARN,
    LOG_TRUNC_40,
    LOG_TRUNC_120,
    LOG_TRUNC_200,
    LOG_TRUNC_300,
    LSP_DIAG_INJECT_LIMIT,
    MEMORY_IMPORTANCE_BASE,
)
from l3.memory.memory_ring import _estimate_tokens
from l3.tool_system.tool_pipeline import get_pipeline

logger = logging.getLogger(__name__)

# Max accumulated content length across truncation, correction, and nudge appends
_AGENT_LOOP_MAX_CONTENT: int = AGENT_LOOP_MAX_CONTENT  # chars (~25K tokens)


class AgentLoopGuardMixin:
    """Pre-send context guard + per-step tool-result processing for AgentLoop."""

    # Host-provided attributes (declared by AgentLoop)
    _cadence: Any
    _cell_id: Any
    _context_trail: Any
    _finish: Any
    _loop_detector: Any
    _pmu: Any
    _repeat_detector: Any
    _run_count: Any
    _truncate_trail: Any
    _user_id: Any
    agent_id: Any
    task: Any

    def _pre_send_compression_guard(
        self, system: str, engine: Any, side_times: dict[str, float], t0: float
    ) -> tuple[int, dict | None]:
        """Three-level pre-send context pressure cascade (stub → compact → CRITICAL).

        Returns ``(ctx_window, early_finish_or_None)`` — a non-None second item
        means the caller must return it immediately (context window exhausted).
        """
        # ── Pre-send compression guard (three-level cascade with PMU + MonitorBus) ──
        _t_guard = time.time()
        ctx_window = 0
        mem = None
        try:
            cw = engine.context_window(cell_id=self._cell_id, agent_id=self.agent_id)
            ctx_window = cw.get("context_window", 0) if isinstance(cw, dict) else int(cw or 0)
        except (AttributeError, NotImplementedError, TypeError, ValueError):
            logger.debug("agent_loop: context window failed")

        def _emit_memory_event(etype: str, data: dict) -> None:
            """Emit a memory event to the monitor bus for cross-Cell observability."""
            try:
                from l3.bus.monitor_bus import MonitorEvent as _ME  # noqa: N814
                from l3.bus.monitor_bus import get_bus as _MB

                _MB().emit(
                    _ME(
                        type=etype,
                        source="agent_loop",
                        severity="info",
                        agent_id=self.agent_id,
                        cell_id=self._cell_id,
                        data=data,
                    )
                )
            except (ImportError, AttributeError):
                logger.debug("agent_loop: monitor bus emit failed")
            try:
                from l3.bus.reference_channel import get_rc as _rc

                _rc().event(
                    "memory_compression",
                    {**data, "type": etype, "agent_id": self.agent_id, "cell_id": self._cell_id},
                    source="agent_loop",
                    trace_id=getattr(self, "_last_card_id", ""),
                )
            except (ImportError, AttributeError):
                logger.debug("agent_loop: reference channel event failed")

        if ctx_window > 0:
            est_tokens = _estimate_tokens(self.task)
            # Include the persistent conversation trail (context_trail) —
            # persistent loops accumulate history across cards/runs; without
            # it the guard underestimates the real request size and history
            # can silently exceed the window.
            trail_tokens = 0
            if self._context_trail:
                trail_tokens = sum(_estimate_tokens(str(m.get("content", ""))) for m in self._context_trail)
            est_total = est_tokens + len(system) // 4 + CONTEXT_BUILD_MAX_TOKENS + trail_tokens
            ratio = est_total / ctx_window
            # Expose the measured pressure to the prompt-library injection
            # (3.2): _context_pressure drives the Cell dynamic-doc auto-hit;
            # _system_load is approximated from the same ratio so the global
            # performance sub-library also engages under load.
            try:
                self._context_pressure = ratio
                self._system_load = ratio
            except AttributeError:
                pass

            # Phase 1: Try compression first (WARN → then MEDIUM escalation)
            if ratio >= CONTEXT_PRESSURE_WARN:
                try:
                    from l3.memory.memory import get_memory

                    mem = get_memory()
                    sr = mem.stub_compact(self.agent_id)
                    logger.info("pre-send L1 stub_compact: ~%d/%d (%.0f%%)", est_total, ctx_window, ratio * 100)
                    if self._pmu:
                        self._pmu.increment("memory.stub_compacts")
                        self._pmu.increment("memory.stub_compact.saved_bytes", sr.get("saved_bytes", 0))
                    _emit_memory_event(
                        "memory.stub_compact",
                        {"ratio": ratio, "stubbed": sr.get("stubbed", 0), "saved_bytes": sr.get("saved_bytes", 0)},
                    )
                    # Re-estimate after stub compaction
                    est_total = _estimate_tokens(self.task) + len(system) // 4 + CONTEXT_BUILD_MAX_TOKENS + trail_tokens
                    ratio = est_total / ctx_window
                except Exception as e:
                    logger.warning("agent_loop L1 stub_compact failed: %s", e)

            if ratio >= CONTEXT_PRESSURE_MEDIUM:
                try:
                    from l3.memory.memory import get_memory as _gm

                    mem = _gm()
                    cr = mem.compact(self.agent_id)
                    mem.forget_agent(self.agent_id, ring=1)
                    # Truncate the persistent conversation trail: keep the
                    # most recent messages, fold older ones into one summary
                    # line — prevents unbounded history growth in persistent
                    # loops (Cell Peer Agents + L3A sessions).
                    trail_removed = self._truncate_trail()
                    logger.info("pre-send L2 compact+forget_R1: ~%d/%d (%.0f%%)", est_total, ctx_window, ratio * 100)
                    if self._pmu:
                        self._pmu.increment("memory.context.warnings")
                        self._pmu.increment("memory.compacts")
                        self._pmu.increment("memory.compact.merges", cr.get("merged", 0))
                        self._pmu.increment("memory.compact.saved_tokens", cr.get("saved_tokens", 0))
                    _emit_memory_event(
                        "memory.compact",
                        {
                            "ratio": ratio,
                            "merges": cr.get("merged", 0),
                            "saved_tokens": cr.get("saved_tokens", 0),
                            "trail_removed": trail_removed,
                        },
                    )
                    # Re-estimate after full compaction
                    trail_tokens = 0
                    if self._context_trail:
                        trail_tokens = sum(_estimate_tokens(str(m.get("content", ""))) for m in self._context_trail)
                    est_total = _estimate_tokens(self.task) + len(system) // 4 + CONTEXT_BUILD_MAX_TOKENS + trail_tokens
                    ratio = est_total / ctx_window
                except Exception as e:
                    logger.warning("agent_loop L2 compact failed: %s", e)

            # Phase 2: Check CRITICAL after compression attempts
            if ratio >= CONTEXT_PRESSURE_CRITICAL:
                from l3.error_bus import capture

                capture(
                    "context window exhausted — aborting agent loop",
                    error_code="E_CTX_EXHAUSTED",
                    component="agent_loop_guard",
                    agent_id=self.agent_id,
                    context={"est_total": est_total, "ctx_window": ctx_window},
                )
                logger.error("context exhausted: ~%d/%d tokens — aborting", est_total, ctx_window)
                if self._pmu:
                    self._pmu.increment("memory.context.critical")
                _emit_memory_event(
                    "memory.pressure.critical", {"ratio": ratio, "est_total": est_total, "ctx_window": ctx_window}
                )
                return ctx_window, self._finish(
                    {
                        "success": False,
                        "answer": "",
                        "error": f"context window exhausted (~{est_total}/{ctx_window} tokens)",
                        "steps": [],
                        "verifier_used": False,
                        "corrections": 0,
                        "loop_stopped": False,
                    },
                    t0=t0,
                )

        # Fallback: when ctx_window is unknown (0), compress every 3 runs
        if ctx_window <= 0 and self._run_count > 0 and self._run_count % 3 == 0:
            try:
                from l3.memory.memory import get_memory

                sr = get_memory().stub_compact(self.agent_id)
                if self._pmu:
                    self._pmu.increment("memory.stub_compacts")
                    self._pmu.increment("memory.stub_compact.saved_bytes", sr.get("saved_bytes", 0))
            except Exception as e:
                logger.warning("agent_loop stub_compact fallback failed: %s", e)
        side_times["compression"] = round(time.time() - _t_guard, 3)
        self._run_count += 1
        return ctx_window, None

    def _process_tool_results(
        self,
        tool_results: list,
        result: dict,
        system: str,
        engine: Any,
        model_kwargs: dict,
        deadline: float,
        verifier: Any | None,
        side_times: dict[str, float],
    ) -> tuple[list, bool, int, bool]:
        """Per-step tool-result processing: timeout, ASK/loop detection, cadence,
        PMU/counter, verifier corrections.

        Returns ``(processed_results, all_passed, corrections, verifier_used)``;
        mutates ``result`` (content/finish_reason) and ``side_times``.
        """
        processed_results: list[dict] = []
        all_passed = True
        corrections = 0
        verifier_used = False
        for step_result in tool_results:
            if time.time() > deadline:
                result["finish_reason"] = "timeout"
                break
            tool_name = step_result.get("name", "unknown") if isinstance(step_result, dict) else "?"

            # ── ASK awaiting: break early when a tool requests user clarification ──
            res_body = step_result.get("result", {}) if isinstance(step_result, dict) else {}
            if isinstance(res_body, dict) and res_body.get("awaiting_input"):
                step_result["_awaiting_input"] = True
                processed_results.append(step_result)
                all_passed = True
                result["finish_reason"] = "awaiting_input"
                break

            if self._loop_detector.check(tool_name, step_result.get("args", {}), step_result) == "stop":
                step_result["_loop_stopped"] = True
                processed_results.append(step_result)
                all_passed = False
                break

            if self._repeat_detector.check(tool_name) == "stop":
                step_result["_loop_stopped"] = True
                processed_results.append(step_result)
                all_passed = False
                break

            # ── LSP diagnostics hook: on tool failure with a file target,
            # fetch line-level diagnostics so the agent can pinpoint the
            # exact line instead of guessing from the error text alone.
            # Runs only after the loop/repeat stop checks so looped steps
            # never pay for an LLM round-trip they will not consume.
            if isinstance(res_body, dict) and res_body.get("error") and res_body.get("file"):
                try:
                    from l4.lsp.lsp_manager import get_manager as _lsp_mgr

                    _diag = _lsp_mgr().get_diagnostics(res_body["file"])
                    if _diag.get("success") and _diag.get("diagnostics"):
                        step_result["_diag"] = _diag["diagnostics"][:LSP_DIAG_INJECT_LIMIT]
                        step_result["_diag_summary"] = _diag.get("summary", "")
                except Exception as e:
                    logger.warning("agent_loop: lsp diagnostics hook failed: %s", e)

            # ── Fix-loop first step: generate a targeted fix suggestion from
            # the line-level diagnostics so the next iteration can apply it
            # directly (closes error → line → fix → re-verify). Deadline
            # guarded so a burst of failing edits cannot overshoot the turn.
            if isinstance(res_body, dict) and step_result.get("_diag") and res_body.get("error"):
                if time.time() > deadline:
                    result["finish_reason"] = "timeout"
                    break
                try:
                    import json as _json

                    _diag_txt = _json.dumps(step_result["_diag"][:3], indent=1)
                    _fix = engine.generate(
                        prompt=(
                            "A tool call failed. Here are line-level diagnostics "
                            f"for {res_body.get('file', '')}:\n{_diag_txt}\n"
                            f"Error: {res_body.get('error', '')}\n"
                            "Propose a precise fix (code change) addressing these "
                            "diagnostics. Reply with a short, actionable fix description."
                        ),
                        system=system,
                        user_id=self._user_id,
                        **model_kwargs,
                    )
                    _fix_content = (str(_fix.get("content", "")) or "")[:LOG_TRUNC_300]
                    if _fix_content:
                        step_result["_diag_fix"] = _fix_content
                        if self._cell_id:
                            try:
                                from l3.cell import get_cell as _get_cell

                                _cell = _get_cell(self._cell_id)
                                _cell.cache.inject(
                                    key=f"fix:{self.agent_id}:{tool_name}:{self.task[:LOG_TRUNC_40]}",
                                    value={
                                        "tool": tool_name,
                                        "file": res_body.get("file", ""),
                                        "error": str(res_body.get("error", ""))[:LOG_TRUNC_200],
                                        "fix": _fix_content,
                                    },
                                    summary=f"FIX [{self.agent_id}] {tool_name}: {_fix_content[:LOG_TRUNC_120]}",
                                    agent_id=self.agent_id,
                                    entry_type="correction",
                                    importance=MEMORY_IMPORTANCE_BASE,
                                )
                            except (ImportError, AttributeError, KeyError):
                                logger.warning("agent_loop: fix memory inject failed")
                except Exception as e:
                    logger.warning("agent_loop: fix suggestion failed: %s", e)

            # Cadence tracking (via ToolConfig)
            try:
                from .tool_system.tool_config import ToolConfig as _TC  # noqa: N814

                if tool_name in _TC.write_tool_names():
                    self._cadence.record_edit(
                        (step_result.get("args", {}) if isinstance(step_result, dict) else {}).get("path", "")
                    )
                if tool_name in _TC.terminal_tool_names():
                    self._cadence.record_check(
                        (step_result.get("args", {}) if isinstance(step_result, dict) else {}).get("command", "")
                    )
            except Exception as e:
                logger.warning("agent_loop cadence tracking failed: %s", e)

            # PMU: tool call counter
            if self._pmu:
                ring_label = "ring_1"
                from l1.kernel.params.kernel import RING_NUM_MAP as _RNM

                try:
                    ts = get_pipeline()._specs.get(tool_name) if hasattr(get_pipeline(), "_specs") else None
                    ts_r = getattr(ts, "ring", None) if ts else None
                    if ts_r:
                        ring_label = _RNM.get(ts_r, "ring_1")
                    self._pmu.increment(f"tools.executed.{ring_label}")
                except (AttributeError, KeyError):
                    self._pmu.increment("tools.executed.ring_1")
            # CellCounter: record tool call (success inferred from no error key)
            try:
                from l3.services.counter import get_counter as _gc

                _gc().record_tool(
                    self.agent_id,
                    tool_name,
                    success="error" not in (step_result.get("result", {}) if isinstance(step_result, dict) else {}),
                )
            except (ImportError, AttributeError) as e:
                logger.warning("agent_loop: tool counter record failed: %s", e)

            if verifier is not None:
                v = verifier.check(step_result, self.task)
                if not v.get("pass") and v.get("retry_allowed"):
                    corrections += 1
                    _t_fix = time.time()
                    try:
                        fix = engine.generate(
                            prompt=verifier.correction_prompt(self.task, [v.get("reason", "")]),
                            system=system,
                            user_id=self._user_id,
                            **model_kwargs,
                        )
                        result["content"] = (result.get("content", "") + "\n" + fix.get("content", ""))[
                            :_AGENT_LOOP_MAX_CONTENT
                        ]
                        verifier_used = True
                        step_result["_corrected"] = True
                        # Persist correction to Cell L2 cache
                        if self._cell_id and v.get("reason"):
                            try:
                                from l3.cell import get_cell as _get_cell

                                cell = _get_cell(self._cell_id)
                                cell.cache.inject(
                                    key=f"correct:{self.agent_id}:{tool_name}:{self.task[:LOG_TRUNC_40]}",
                                    value={
                                        "tool": tool_name,
                                        "error": v.get("reason", ""),
                                        "fix": fix.get("content", "")[:LOG_TRUNC_300],
                                    },
                                    summary=f"CORRECT [{self.agent_id}] {tool_name}: {v.get('reason', '')[:LOG_TRUNC_120]}",
                                    agent_id=self.agent_id,
                                    entry_type="correction",
                                    importance=MEMORY_IMPORTANCE_BASE,
                                )
                            except (ImportError, AttributeError, KeyError):
                                logger.debug("agent_loop: correction memory failed")
                    except Exception as e:
                        logger.warning("agent_loop verifier correction failed: %s", e)
                    finally:
                        side_times["continuation"] += time.time() - _t_fix

            processed_results.append(step_result)
        return processed_results, all_passed, corrections, verifier_used
