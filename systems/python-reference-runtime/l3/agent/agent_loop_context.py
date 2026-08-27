"""AgentLoop context mixin — system-prompt construction and R4 context injection.

Extracted from ``agent_loop.py`` (AgentLoop) to slim the class: prompt
template resolution, chat-params hooks, todowrite registration, and the
R4 lean-case / evolved-skill / cross-cell-rule injection with bounded
token budget. ``AgentLoop`` inherits this mixin so runtime behavior is
unchanged.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from l1.kernel.params.agent import (
    LOOP_CONTEXT_BUDGET_SKILL,
    LOOP_EVOLVED_SKILLS_LIMIT,
    LOOP_LEAN_CASES_LIMIT,
    R4_CARD_SKILL_SIGNAL_MAX,
)
from l1.kernel.params.kernel import RING_1
from l1.kernel.params.system import LOG_TRUNC_40, LOG_TRUNC_200, SKILL_POSTURE_OFFENSIVE
from l3.agent.prompts import get_prompt
from l3.tool_system.tool_spec import ParamSpec, ToolSpec

logger = logging.getLogger(__name__)


def _inject_enabled(domain: str) -> bool:
    """Whether the ``prompt.inject.<domain>`` system-prompt injection is on."""
    from l1.kernel.settings import inject_enabled as _ie

    return _ie(domain)


class AgentLoopContextMixin:
    """System-prompt assembly and R4-driven context injection for AgentLoop."""

    # Host-provided attributes (declared by AgentLoop)
    _cell_id: Any
    _chat_params_hooks: Any
    _pmu: Any
    _prompt_key: Any
    _role: Any
    _system: Any
    _todo: Any
    _tools: Any
    _wrap_handler: Any
    agent_id: Any
    task: Any

    def _card_query_boost(self) -> str:
        """Build the tag-boost fragment appended to the retrieval query."""
        tags = getattr(self, "_card_tags", []) or []
        if not tags:
            return ""
        return " " + " ".join(tags)

    def _resolve_model_kwargs(self, model_config: dict | None) -> dict:
        """Extract model kwargs from config and apply chat-params hooks."""
        model_kwargs: dict = {}
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
        return model_kwargs

    def _resolve_base_system(self, max_steps: int) -> str:
        """Resolve the base system prompt (explicit, role-keyed, or default template)."""
        todo_reminder = self._todo.reminder()

        if self._system:
            system = self._system
        else:
            pk = self._prompt_key
            if not pk and self._role:
                # Prefer the role's configured system_prompt_key (params
                # DEFAULT_AGENT_CONFIGS / praxis.yaml agents:), falling back
                # to the implicit agent_loop.system.{role} convention.
                try:
                    from l1.kernel.params.agent import DEFAULT_AGENT_CONFIGS

                    cfg = DEFAULT_AGENT_CONFIGS.get(self._role)
                    if cfg and cfg.system_prompt_key:
                        pk = cfg.system_prompt_key
                except Exception:
                    pass
            if not pk and self._role:
                pk = f"agent_loop.system.{self._role}"
            if not pk:
                pk = "agent_loop.system"
            template = get_prompt(pk, get_prompt("agent_loop.system", ""))
            system = template.format(task=self.task) + get_prompt(
                "agent_loop.turn_budget", "\nYou have up to {max_steps} tool-calling turns. Use them wisely."
            ).format(max_steps=max_steps)
        vc = get_prompt("agent_loop.verification_culture", "")
        if vc and _inject_enabled("verification"):
            system = (system + "\n\n" + vc) if system else vc
        if todo_reminder:
            system = (system + "\n\n" + todo_reminder) if system else todo_reminder
        return system

    def _inject_constitution(self, system: str) -> str:
        """Append the constitutional summary (inject-gated, non-fatal)."""
        try:
            from l1.kernel.constitution import get_constitution

            if _inject_enabled("constitution"):
                const_summary = get_constitution().summary(for_agent=self.agent_id)
                system = (system + "\n\n" + const_summary) if system else const_summary
        except (ImportError, AttributeError):
            logger.debug("agent_loop: constitution summary failed")
        return system

    def _inject_identity_role(self, system: str) -> str:
        """Append the Cell's role-bound strict-role fragment (Phase 1)."""
        try:
            from l1.kernel.identity_binding import get_identity_binding_manager

            if _inject_enabled("identity"):
                fragment = get_identity_binding_manager().resolve_fragment(self._cell_id, self._role)
                if fragment:
                    system = (system + "\n\n" + fragment) if system else fragment
        except (ImportError, AttributeError):
            logger.debug("agent_loop: identity binding injection failed")
        return system

    def _inject_identity_htn(self, system: str) -> str:
        """Append the HTN-C task-intent identity fragment (A2, non-fatal)."""
        try:
            from l3.bus.htn_planner import match_identity

            if _inject_enabled("identity"):
                _task_intent = getattr(self, "_task_intent", "") or ""
                if _task_intent:
                    _matched = match_identity(_task_intent, domain=getattr(self, "_task_domain", ""))
                    if _matched:
                        _id_frag = get_prompt(f"identity.{_matched}.fragment", "")
                        if _id_frag:
                            system = (system + "\n\n" + _id_frag) if system else _id_frag
        except Exception as e:
            logger.debug("agent_loop: HTN-C identity injection failed: %s", e)
        return system

    def _inject_identity_card_domain(self, system: str) -> str:
        """Append the card-domain expert fragment (card-domain linkage)."""
        try:
            from l1.kernel.identity_binding import get_identity_binding_manager

            if _inject_enabled("identity"):
                _card_domain = getattr(self, "_card_domain", "") or ""
                if _card_domain:
                    _domain_frag = get_identity_binding_manager().resolve_domain_fragment(self._cell_id, _card_domain)
                    if _domain_frag:
                        system = (system + "\n\n" + _domain_frag) if system else _domain_frag
        except Exception as e:
            logger.debug("agent_loop: card-domain identity injection failed: %s", e)
        return system

    def _inject_cell_handbook(self, system: str) -> str:
        """Append the per-Cell Agents handbook (Phase 3 M3, inject-gated)."""
        try:
            if _inject_enabled("skills") and self._cell_id:
                from l3.memory.tiered_cache import get_tiered_cache

                _meta = get_tiered_cache().get_archive_index(f"cell:{self._cell_id}:agents_md") or {}
                _text = str(_meta.get("content", "")) or ""
                if _text:
                    system = (system + "\n\n" + _text[:LOOP_CONTEXT_BUDGET_SKILL]) if system else _text
        except Exception as e:
            logger.debug("agent_loop: per-Cell handbook injection failed: %s", e)
        return system

    def _inject_cell_prompt_library(self, system: str) -> str:
        """Append the Cell-domain shared prompt library (Phase 3.2)."""
        try:
            if self._cell_id:
                from l3.agent.prompt_library import prompt_library_status, resolve_cell_prompt

                if prompt_library_status().get("enabled"):
                    _pressure = float(getattr(self, "_context_pressure", 0.0) or 0.0)
                    _lib_text = resolve_cell_prompt(self._cell_id, pressure=_pressure)
                    if _lib_text:
                        system = (system + "\n\n" + _lib_text) if system else _lib_text
        except Exception as e:
            logger.debug("agent_loop: Cell prompt-library injection failed: %s", e)
        return system

    def _inject_test_matrix(self, system: str) -> str:
        """Append the prebuilt test matrix for the driving card (tester role).

        Phase 3.1: only the testing department's AgentLoop (role ``tester``)
        consumes the prebuilt matrix. Reads the bounded matrix from the
        tiered-cache L2 layer (``test_matrix_prebuild.get_matrix``); when
        prebuild is off, the cache misses, or no card is bound, the injection
        is skipped (or falls back to a synchronous build) — never raises.
        """
        try:
            if (getattr(self, "_role", "") or "") != "tester":
                return system
            _card_id = getattr(self, "_last_card_id", "") or ""
            if not _card_id:
                return system
            from l3.cell.test_matrix_prebuild import get_matrix, prebuild_enabled

            if not prebuild_enabled():
                return system
            _cell_id = getattr(self, "_cell_id", "") or ""
            _domain = str(getattr(self, "_card_domain", "") or "")
            matrix = get_matrix(
                _cell_id,
                _card_id,
                intent=getattr(self, "task", "") or "",
                domain=_domain,
            )
            if not matrix:
                return system
            lines = "\n".join(
                f"  {r.get('entry', i)}. [{r.get('case', '?')}] {r.get('expect', '')}" for i, r in enumerate(matrix)
            )
            block = f"\n\n--- Test Matrix ---\n{lines}\n---"
            # Explicit budget: keep the injection bounded even if the matrix
            # grows (per-field truncation + row cap already bound it, this is
            # the same defense-in-depth style as LOOP_CONTEXT_BUDGET_SKILL).
            if len(block) > LOOP_CONTEXT_BUDGET_SKILL:
                block = block[:LOOP_CONTEXT_BUDGET_SKILL]
            system = (system + "\n\n" + block) if system else block
        except Exception as e:
            logger.debug("agent_loop: test-matrix injection failed: %s", e)
        return system

    def _inject_global_prompt_library(self, system: str) -> str:
        """Append the global shared prompt library (Phase 3.2, load+domain driven)."""
        try:
            from l3.agent.global_prompt_library import (
                global_prompt_library_status,
                resolve_global_prompt,
            )

            if global_prompt_library_status().get("enabled"):
                _load = float(getattr(self, "_system_load", 0.0) or 0.0)
                _domain = str(getattr(self, "_card_domain", "") or "")
                _global_text = resolve_global_prompt(load=_load, domain=_domain)
                if _global_text:
                    system = (system + "\n\n" + _global_text) if system else _global_text
        except Exception as e:
            logger.debug("agent_loop: global prompt-library injection failed: %s", e)
        return system

    def _inject_system_extras(self, system: str) -> str:
        """Append all gated OS-managed fragments in assembly order."""
        system = self._inject_constitution(system)
        system = self._inject_identity_role(system)
        system = self._inject_identity_htn(system)
        system = self._inject_identity_card_domain(system)
        system = self._inject_cell_handbook(system)
        system = self._inject_cell_prompt_library(system)
        system = self._inject_test_matrix(system)
        return self._inject_global_prompt_library(system)

    def _wrap_presentation_tools(self) -> tuple[list, list, bool]:
        """Filter/wrap model-facing tools by presentation mode; returns (wrapped, read_only, code_mode)."""
        from l1.kernel.params.tool import (
            TOOL_PRESENTATION_BOTH,
            TOOL_PRESENTATION_CODE,
            TOOL_PRESENTATION_NATIVE,
        )
        from l3.tool_system.tool_presentation import get_presentation_mode

        presentation = get_presentation_mode()
        code_mode = presentation in (TOOL_PRESENTATION_CODE, TOOL_PRESENTATION_BOTH)
        wrapped_tools = []
        read_only_tools = []
        for t in self._tools:
            is_run_code = t.name == "run_code"
            if presentation == TOOL_PRESENTATION_NATIVE and is_run_code:
                continue  # native mode does not expose the reserved transport
            if presentation == TOOL_PRESENTATION_CODE and not is_run_code:
                continue  # code mode exposes only the run_code transport
            wrapped = ToolSpec(
                name=t.name,
                description=t.description,
                category=t.category,
                ring=t.ring,
                danger=t.danger,
                parameters=t.parameters,
                handler=self._wrap_handler(t),
                parallel_safe=t.parallel_safe,
            )
            wrapped_tools.append(wrapped)
            if t.parallel_safe:
                read_only_tools.append(wrapped)
        return wrapped_tools, read_only_tools, code_mode

    def _assemble_code_mode(self, system: str, code_mode: bool) -> str:
        """Assemble the byte-stable code-mode prefix (SDK + usage) when exposed."""
        if not code_mode:
            return system
        from l3.tool_system.tool_presentation import assemble_code_prompt, get_language_backend

        backend = get_language_backend()
        if backend is None:
            return system
        sdk = backend.render_sdk(
            [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": [
                        {"name": p.name, "type": p.type, "description": p.description} for p in (t.parameters or [])
                    ],
                }
                for t in self._tools
            ]
        )
        # Language-specific usage from the backend; a praxis.yaml
        # prompt override (agent_loop.run_code_usage) wins if present.
        # Monitored getter: counts usage for the bypass monitor
        # (engineering/debug mode, 3.2).
        from l3.agent.prompts import get_prompt_monitored

        usage = get_prompt_monitored("agent_loop.run_code_usage", "") or backend.render_usage()
        # Stable-prefix assembly: system + usage + SDK form the
        # byte-stable prefix every request reuses (vendor KV-cache
        # hits); the incremental suffix (program/patch/results) is
        # appended later by the conversation.
        return assemble_code_prompt(system, sdk, usage)

    def _build_run_context(
        self, max_steps: int, model_config: dict | None, engine: Any
    ) -> tuple[str, list, list, dict]:
        """Build system prompt, wrap tools, and prepare model kwargs."""
        model_kwargs = self._resolve_model_kwargs(model_config)

        self._register_todowrite()
        self._register_tool_result_read()
        system = self._resolve_base_system(max_steps)
        system = self._inject_system_extras(system)

        # Tool presentation (Code Mode / PTC): filter the model-facing tools by
        # the presentation mode and inject the run_code SDK + usage when the
        # transport is exposed. ``native`` (default) hides run_code; ``code``
        # exposes only it (tools:code-only); ``both`` exposes everything.
        # The language backend owns the SDK and usage text — the framework
        # never hardcodes a language.
        wrapped_tools, read_only_tools, code_mode = self._wrap_presentation_tools()
        system = self._assemble_code_mode(system, code_mode)
        return system, wrapped_tools, read_only_tools, model_kwargs

    def _inject_extra_context(self, system: str) -> str:
        """Inject R4 lean cases, evolved skills, and cross-cell rules into system prompt.

        Token budget is bounded by ``LOOP_CONTEXT_BUDGET_SKILL`` to avoid
        overflowing the context window with skill content. Gated by the
        ``prompt.inject.skills`` setting (user-configurable).
        """
        if not _inject_enabled("skills"):
            return system
        try:
            from l3.memory.r4_agent import get_r4_agent

            r4 = get_r4_agent()
            budget = LOOP_CONTEXT_BUDGET_SKILL
            lean = r4.get_lean_cases(agent_id=self.agent_id, cell_id=self._cell_id, limit=LOOP_LEAN_CASES_LIMIT)
            injected: list[str] = []
            if lean:
                # All returned lean cases are injected (full or truncated), so
                # their names ride the same cache — no extra registry scan.
                injected = list(
                    r4.get_lean_case_names(agent_id=self.agent_id, cell_id=self._cell_id, limit=LOOP_LEAN_CASES_LIMIT)
                )
                lines = "\n".join(f"  {i}. {lc}" for i, lc in enumerate(lean, 1))
                block = f"\n\n--- Known Failure Patterns ---\n{lines}\n---"
                if len(block) <= budget:
                    system += block
                    budget -= len(block)
                else:
                    truncated = "\n".join(f"  {i}. {lc[:LOG_TRUNC_200]}" for i, lc in enumerate(lean, 1))
                    system += f"\n\n--- Known Failure Patterns (truncated) ---\n{truncated}\n---"
            # Task-similarity retrieval (tf-idf, zero deps): rank evolved
            # skills by relevance to the current task before injection;
            # falls back to loaded_at ordering when disabled or low-score.
            # getattr guard: tests may construct AgentLoop via __new__ (no
            # __init__), so task may be absent — empty query = loaded_at order.
            # Card linkage: card-derived tags (nature/domain) are appended to
            # the query so the same task text under different card types can
            # surface different skills (e.g. review vs deploy cards).
            evolved = r4.retrieve_skills(
                query=(getattr(self, "task", "") or "") + self._card_query_boost(),
                agent_id=self.agent_id,
                cell_id=self._cell_id,
                role=getattr(self, "_role", ""),
                limit=LOOP_EVOLVED_SKILLS_LIMIT,
                tags=getattr(self, "_card_tags", []) or [],
            )
            if evolved and budget > 0:
                for es in evolved:
                    # Audience routing: user-invoked skills and skills tagged
                    # for another domain are excluded from automatic context
                    # injection — they fire only on explicit use within their
                    # own domain (dynamic supply, not blanket injection).
                    if es.get("disable_model_invocation"):
                        continue
                    from l1.kernel.skill import get_skill_manager as _loop_sm
                    from l1.kernel.skill import skill_visible

                    if not skill_visible(es, self.agent_id):
                        continue
                    # Posture gate (default-deny, runtime policy): offensive
                    # skills are only injected when the SkillManager
                    # offensive-policy authorizes the driving card nature
                    # (L3A decision layer). The gate can be bypassed at
                    # runtime by disabling the policy (soft control).
                    if es.get("posture") == SKILL_POSTURE_OFFENSIVE and not _loop_sm().offensive_authorized(
                        getattr(self, "_card_nature", "")
                    ):
                        # P1: record posture-gate injection blocks in StatsCenter.
                        try:
                            from l3.tool_system.security_mode import ingest_security_metric

                            ingest_security_metric(
                                "security.gate.injection.blocked",
                                tags={"skill": es.get("name", ""), "nature": getattr(self, "_card_nature", "")},
                            )
                        except Exception:
                            pass
                        # Evidence chain: block decisions anchor to the active
                        # posture chain with the skill/nature detail.
                        try:
                            from l3.tool_system.security_evidence import DECISION_BLOCK, record_evidence

                            record_evidence(
                                phase="injection",
                                gate="posture_injection",
                                decision=DECISION_BLOCK,
                                target=es.get("name", ""),
                                source="agent_loop",
                                tags={"nature": getattr(self, "_card_nature", "")},
                            )
                        except Exception:
                            pass
                        continue
                    # Structured injection: name + description + rule count —
                    # the markdown body stays on the human/review layer.
                    rules_count = es.get("rules") or 0
                    block = f"\n\n### {es['name']}\n{es['description']} ({rules_count} rules)"
                    # Full guidance mode: annotate the active atomic unit for
                    # staged skills (quest-log style, e.g. tdd:red).
                    try:
                        from l1.kernel.skill import get_skill_manager as _gm

                        if _gm().guidance_policy().get("mode", "full") == "full" and es.get("stages"):
                            session_key = (
                                self.skill_session_key() if hasattr(self, "skill_session_key") else self.agent_id
                            )
                            cur = _gm().current_stage(es["name"], session_key)
                            if cur.get("staged"):
                                block += f" [unit {es['name']}:{cur['stage'].get('id', '')}]"
                    except Exception:
                        pass
                    if len(block) <= budget:
                        system += block
                        budget -= len(block)
                        injected.append(es["name"])
                        if es.get("posture") == SKILL_POSTURE_OFFENSIVE:
                            try:
                                from l3.tool_system.security_mode import ingest_security_metric

                                ingest_security_metric(
                                    "security.gate.injection.allowed",
                                    tags={"skill": es.get("name", ""), "nature": getattr(self, "_card_nature", "")},
                                )
                            except Exception:
                                pass
                            # Evidence chain: granted offense injection; a
                            # disabled policy is flagged as a soft bypass.
                            try:
                                from l3.tool_system.security_evidence import (
                                    DECISION_ALLOW,
                                    DECISION_BYPASS,
                                    record_evidence,
                                )

                                pol_enabled = _loop_sm().offensive_policy().get("enabled", True)
                                record_evidence(
                                    phase="injection",
                                    gate="posture_injection",
                                    decision=DECISION_ALLOW if pol_enabled else DECISION_BYPASS,
                                    target=es.get("name", ""),
                                    source="agent_loop",
                                    tags={
                                        "nature": getattr(self, "_card_nature", ""),
                                        "soft_bypass": "0" if pol_enabled else "1",
                                    },
                                )
                            except Exception:
                                pass
                        if getattr(self, "_pmu", None):
                            try:
                                self._pmu.increment("skills.evolved.injected")
                            except Exception:
                                logger.debug("agent_loop: pmu increment failed, skipped", exc_info=True)
                    else:
                        # Partial: only include name + description
                        system += f"\n\n### {es['name']}\n{es['description']}"
                        injected.append(es["name"])
                        break
            # Injection feedback: refresh last_used for every injected skill so
            # the R4Agent TTL prune never deletes skills that are actively
            # exposed to agents.  Usage-only update — no write clearance, no
            # revision bump (the R4Agent injection cache stays hot).  Also
            # records inject_count — the denominator of the curation
            # contribution score (useful/injected).
            if injected:
                try:
                    from l1.kernel.skill import get_skill_manager
                    from l3.memory.skill_guidance import materialize_stage_todo

                    _sm = get_skill_manager()
                    _now = time.time()
                    for _name in injected:
                        _sm.update(_name, {"last_used": _now})
                        _sm.bump_usage(_name, key="inject_count")
                        _todo = getattr(self, "_todo", None)
                        if _todo is not None:
                            try:
                                materialize_stage_todo(
                                    _todo,
                                    _sm,
                                    _name,
                                    session_key=self.skill_session_key()
                                    if hasattr(self, "skill_session_key")
                                    else self.agent_id,
                                )
                            except Exception:
                                logger.debug("agent_loop: stage TODO materialize skipped", exc_info=True)
                        # Card→skill signal: injected skills ride the current
                        # card's preference attribution (bounded set).
                        _used = getattr(self, "_card_skills_used", None)
                        if _used is not None and len(_used) < R4_CARD_SKILL_SIGNAL_MAX:
                            _used.add(_name)
                except Exception as e:
                    logger.debug("agent_loop: skill last_used refresh failed: %s", e)
        except Exception as e:
            logger.warning("agent_loop context injection failed: %s", e)
        try:
            from l3.cell.peers.l3 import get_coordinator

            coord = get_coordinator()
            if getattr(coord, "_cross_cell_active", False):
                system += get_prompt("agent_loop.cross_cell_rules", "")
        except Exception as e:
            logger.warning("agent_loop context injection failed: %s", e)
        return system

    def _register_todowrite(self) -> None:
        """Register the todowrite tool for task-list management."""

        def _todowrite_handler(args: dict, agent_id: str = "") -> dict:
            """Handle a todowrite tool call — update todo item status.

            Three-table linkage: a stage TODO ('[skill:<name>:<stage_id>] …')
            reaching 'verified' advances the skill's stage for this session.
            """
            content = args.get("content", "")
            status = args.get("status", "in_progress")
            self._todo.update(content, status)
            # Three-table linkage (TODO × card × skill): a task named after a
            # skill (or reaching 'verified') bumps that skill's usage count.
            # Non-fatal — linkage must degrade gracefully.
            if status == "verified":
                try:
                    from l1.kernel.skill import get_skill_manager

                    sm = get_skill_manager()
                    if content.startswith("[skill:") and "]" in content:
                        skill_name = content[7 : content.index("]")].split(":", 1)[0]
                        if skill_name:
                            sm.bump_usage(skill_name, key="todo_verified")
                    else:
                        sm.bump_usage_for_tools([content])
                except Exception as e:
                    logger.debug("skill usage bump skipped: %s", e)
            advanced = 0
            if status == "verified" and content.startswith("[skill:"):
                try:
                    from l1.kernel.skill import get_skill_manager
                    from l3.memory.skill_guidance import advance_on_stage_todo_verified

                    advanced = advance_on_stage_todo_verified(
                        self._todo,
                        get_skill_manager(),
                        content,
                        session_key=self.skill_session_key() if hasattr(self, "skill_session_key") else agent_id,
                    ).get("advanced", 0)
                except Exception as e:
                    logger.debug("skill stage advance skipped: %s", e)
            message = f"todo '{content[:LOG_TRUNC_40]}' → {status}"
            if advanced:
                message += " (skill stage advanced)"
            return {"success": True, "message": message}

        # Only register if not already added
        if not any(t.name == "todowrite" for t in self._tools):
            self._tools.append(
                ToolSpec(
                    name="todowrite",
                    description="Update task list status. status: pending|in_progress|completed. Use 'add' for new items.",
                    category="generic",
                    ring=RING_1,
                    danger=0,
                    parameters=[
                        ParamSpec("content", "string", required=True, description="Task description"),
                        ParamSpec("status", "string", required=True, description="pending|in_progress|completed|add"),
                    ],
                    handler=_todowrite_handler,
                    parallel_safe=False,
                )
            )

    def _register_tool_result_read(self) -> None:
        """Register the tool_result_read tool for offload-cache read-back.

        When the tool-result offload cache is enabled and a large result was
        offloaded, the trail keeps only a reference line (call_id + digest).
        This tool lets the model fetch the full structured payload on demand,
        bounded by TOOL_RESULT_READBACK_MAX_CHARS so one read cannot flood
        the context window. Absent entries degrade to an empty result.
        """

        def _tool_result_read_handler(args: dict, agent_id: str = "") -> dict:
            """Handle a tool_result_read call — fetch an offloaded payload."""
            call_id = str(args.get("call_id", "") or "")
            if not call_id:
                return {"success": False, "error": "call_id is required"}
            try:
                from l1.kernel.params.system import TOOL_RESULT_READBACK_MAX_CHARS
                from l3.agent.tool_result_cache import fetch_result

                entry = fetch_result(self._cell_id, call_id)
                if not entry:
                    return {
                        "success": False,
                        "error": f"no offloaded result for call_id '{call_id}' (expired or disabled)",
                    }
                payload = entry.get("result", {})
                text = str(payload)
                if len(text) > TOOL_RESULT_READBACK_MAX_CHARS:
                    payload = {
                        "truncated": True,
                        "note": f"result exceeds read-back budget ({TOOL_RESULT_READBACK_MAX_CHARS} chars); "
                        "use targeted tools (read/grep) for specific portions",
                        "head": text[: TOOL_RESULT_READBACK_MAX_CHARS // 2],
                        "tail": text[-(TOOL_RESULT_READBACK_MAX_CHARS // 2) :],
                    }
                return {"success": True, "tool": entry.get("tool", ""), "call_id": call_id, "result": payload}
            except Exception as e:
                logger.debug("tool_result_read failed: %s", e)
                return {"success": False, "error": "read-back unavailable"}

        if not any(t.name == "tool_result_read" for t in self._tools):
            self._tools.append(
                ToolSpec(
                    name="tool_result_read",
                    description=(
                        "Fetch the full payload of an offloaded tool result by call_id. "
                        "When a tool result was offloaded (reference line with call_id), "
                        "use this to retrieve the complete structured output on demand."
                    ),
                    category="generic",
                    ring=RING_1,
                    danger=0,
                    parameters=[
                        ParamSpec(
                            "call_id",
                            "string",
                            required=True,
                            description="The offload reference call_id from the tool result",
                        ),
                    ],
                    handler=_tool_result_read_handler,
                    parallel_safe=True,
                )
            )
