"""L2 Shell: system commands (status, devices, process, history, lang, clear, help)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from l2.i18n import t as _t

logger = logging.getLogger(__name__)


def _cmd_status(args: list[str], session=None) -> dict:
    from l1.kernel.healthcheck import safe_system_check as _health
    from l1.kernel.process import get_table
    from l2.i18n import t
    from l3.agent_terminal import get_terminals

    h = _health()
    print(t("shell.status.kernel_health", status=h.get("status", "?"), modules=h.get("module_count", 0)))
    for name, r in h.get("subsystems", {}).items():
        print(f"  [{r['status']}] {name}")
    print(f"\n{t('shell.status.processes', count=len(get_table().list_processes()))}")
    print(t("shell.status.terminals", count=len(get_terminals())))
    try:
        from l1.kernel.lifecycle import get_lifecycle

        lc = get_lifecycle()
        rec = lc.load()
        print(
            t(
                "shell.status.lifecycle",
                state=lc.state().value,
                boots=rec.boot_count,
                schema=rec.schema_version or "unset",
            )
        )
    except Exception:
        logger.debug("system: lifecycle load failed, skipping", exc_info=True)
    # Enrich with shell mode/cell context (agent_id only present in Direct mode)
    result = dict(h)
    try:
        from ..state import get_state

        st = session if session is not None else get_state()
        result["mode"] = st.mode
        result["cell_id"] = st.cell_id
        if st.is_direct():
            result["agent_id"] = st.agent_id
    except Exception:
        logger.debug("system: shell state enrichment failed", exc_info=True)
    return result


def _cmd_intents(args: list[str], session=None) -> dict:
    from l3.scheduler.think_registry import get_think_registry

    reg = get_think_registry()
    return {"success": True, "intents": reg.stats()}


def _cmd_scheduler(args: list[str], session=None) -> dict:
    from l3.scheduler.scheduler import get_scheduler

    s = get_scheduler()
    return {"success": True, "data": s.stats() if hasattr(s, "stats") else {}}


def _cmd_observe(args: list[str], session=None) -> dict:
    from l3.bus.observability_bus import get_obs_bus

    return {"success": True, "data": get_obs_bus().summary()}


def _parse_skill_args(args: list[str]) -> tuple[str, str, list[str]]:
    """Split ``--role``/``--agent`` flags from the positional skill args."""
    role = ""
    agent_id = ""
    rest: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--role", "--agent") and i + 1 < len(args):
            if a == "--role":
                role = args[i + 1]
            else:
                agent_id = args[i + 1]
            i += 2
        else:
            rest.append(a)
            i += 1
    return role, agent_id, rest


def _skills_list(sm, rest: list[str]) -> dict:
    """List skills (default subcommand)."""
    from l1.kernel.params.system import SKILL_LIST_DISPLAY_LIMIT

    skills = sm.list_skills()
    return {"success": True, "skills": skills[:SKILL_LIST_DISPLAY_LIMIT], "count": len(skills)}


def _skills_lean(sm, rest: list[str]) -> dict:
    """List lean-case skills."""
    from l1.kernel.params.system import SKILL_LIST_DISPLAY_LIMIT

    skills = sm.list_skills(tags=["lean_case"])
    return {"success": True, "skills": skills[:SKILL_LIST_DISPLAY_LIMIT], "count": len(skills)}


def _skills_get(sm, rest: list[str]) -> dict:
    """Show a single skill's detail."""
    name = rest[1] if len(rest) > 1 else ""
    if not name:
        return {"success": False, "error": _t("shell.app_error.usage_skills_get")}
    skill = sm.get(name)
    if not skill:
        return {"success": False, "error": _t("shell.app_error.skill_not_found", name=name)}
    return {"success": True, "skill": skill}


def _skills_permissions(sm, rest: list[str]) -> dict:
    """Show the SkillManager write-gate policy."""
    # Policy lives on the SkillManager (L1) — L2 must not import L3.
    policy = sm.write_policy()
    return {"success": True, "policy": policy}


def _skills_distill(sm, rest: list[str]) -> dict:
    """Distillation / DPO master switches (status public; toggling developer-only)."""
    action = rest[1] if len(rest) > 1 else "status"
    if action == "status":
        return {"success": True, "policy": sm.distill_policy()}
    if action in ("set", "on", "off"):
        field = rest[2] if len(rest) > 2 else ""
        value = rest[3] if len(rest) > 3 else ""
        valid_fields = ("distill", "dpo_signal", "generalize", "llm_distill", "clustering", "sampling")
        if field not in valid_fields or value not in ("on", "off", "true", "false", "1", "0"):
            return {
                "success": False,
                "error": _t("shell.app_error.usage_skills_distill"),
            }
        flag = value in ("on", "true", "1")
        if field == "distill":
            return sm.set_distill_policy(distill=flag, source="shell")
        if field == "dpo_signal":
            return sm.set_distill_policy(dpo_signal=flag, source="shell")
        return sm.set_distill_policy(sub={field: flag}, source="shell")
    return {
        "success": False,
        "error": _t("shell.app_error.unknown_action", domain="distill", action=action),
        "suggestions": ["status", "set <distill|dpo_signal|generalize|llm_distill|clustering|sampling> <on|off>"],
    }


def _candidate_policy(sm, store, rest: list[str], role: str, agent_id: str) -> dict:
    """Read or update candidate generation policy."""
    if len(rest) == 2:
        return {"success": True, "policy": store.status()}
    value = rest[2] if len(rest) > 2 else ""
    valid = ("on", "off", "true", "false", "1", "0")
    if value not in valid:
        return {"success": False, "error": _t("shell.app_error.usage_skills_candidates_policy")}
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": _t("shell.app_error.permission_denied", who=who)}
    return store.set_enabled(value in ("on", "true", "1"))


def _candidate_transition(sm, store, action: str, rest: list[str], role: str, agent_id: str) -> dict:
    """Apply a lifecycle transition after checking the write gate."""
    candidate_id = rest[2] if len(rest) > 2 else ""
    valid_actions = ("validate", "publish", "activate", "retire")
    if action not in valid_actions or not candidate_id:
        return {"success": False, "error": _t("shell.app_error.usage_skills_candidates")}
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": _t("shell.app_error.permission_denied", who=who)}
    transitions = {
        "validate": lambda: store.validate(candidate_id),
        "publish": lambda: store.publish(candidate_id, " ".join(rest[3:])),
        "activate": lambda: store.activate(candidate_id),
        "retire": lambda: store.retire(candidate_id),
    }
    return transitions[action]()


def _skills_candidates(sm, rest: list[str], role: str, agent_id: str) -> dict:
    """Control the evidence-backed R4 candidate lifecycle through its L1 port."""
    from l1.kernel.ports import get_port

    try:
        store = get_port("r4_candidates")
    except KeyError:
        return {"success": False, "error": _t("shell.app_error.r4_candidate_ledger_unavailable")}
    action = rest[1] if len(rest) > 1 else "list"
    if action in ("list", "ls"):
        state = rest[2] if len(rest) > 2 else ""
        candidates = store.list_candidates(state=state)
        return {"success": True, "candidates": candidates, "count": len(candidates), "policy": store.status()}
    if action == "policy":
        return _candidate_policy(sm, store, rest, role, agent_id)
    return _candidate_transition(sm, store, action, rest, role, agent_id)


def _skills_retriever(sm, rest: list[str]) -> dict:
    """Skill retriever backend control (tfidf | embedding)."""
    action = rest[1] if len(rest) > 1 else "status"
    from l3.memory.skill_retriever import retriever_status, set_backend

    if action == "status":
        return retriever_status()
    if action == "set":
        backend = rest[2] if len(rest) > 2 else ""
        if not backend:
            return {"success": False, "error": _t("shell.app_error.usage_skills_retriever")}
        return set_backend(backend)
    return {
        "success": False,
        "error": _t("shell.app_error.unknown_action", domain="retriever", action=action),
        "suggestions": ["status", "set <tfidf|embedding>"],
    }


def _skills_pipeline_set(sm, rest: list[str]) -> dict:
    """`skills pipeline set <field> <value>` — tune retrieval/curation policy."""
    field = rest[2] if len(rest) > 2 else ""
    value = rest[3] if len(rest) > 3 else ""
    if field in ("retrieval", "curation") and value in ("on", "off", "true", "false", "1", "0"):
        flag = value in ("on", "true", "1")
        return sm.set_pipeline_policy(**{field: flag}, source="shell")
    if field == "contrib_min_trials" and value.isdigit():
        return sm.set_pipeline_policy(contrib_min_trials=int(value), source="shell")
    if field in ("contrib_min_ratio", "retrieval_min_score"):
        try:
            fv = float(value)
        except ValueError:
            return {"success": False, "error": _t("shell.app_error.usage_skills_pipeline_invalid_number")}
        return sm.set_pipeline_policy(**{field: fv}, source="shell")
    return {
        "success": False,
        "error": _t("shell.app_error.invalid_field_value", domain="pipeline", field=field, value=value),
        "suggestions": [
            "status",
            "set <retrieval|curation> <on|off>",
            "set <contrib_min_trials|contrib_min_ratio|retrieval_min_score> <number>",
        ],
    }


def _skills_pipeline(sm, rest: list[str]) -> dict:
    """Retrieval/curation pipeline policy (status public; tuning developer-only)."""
    action = rest[1] if len(rest) > 1 else "status"
    if action == "status":
        return {"success": True, "policy": sm.pipeline_policy()}
    if action == "set":
        return _skills_pipeline_set(sm, rest)
    return {
        "success": False,
        "error": _t("shell.app_error.unknown_action", domain="pipeline", action=action),
        "suggestions": ["status", "set <field> <value>"],
    }


def _skills_disclosure(sm, rest: list[str]) -> dict:
    """Progressive-disclosure policy (status public; toggling developer-only)."""
    action = rest[1] if len(rest) > 1 else "status"
    if action == "status":
        return {"success": True, "policy": sm.disclosure_policy()}
    if action == "set":
        field = rest[2] if len(rest) > 2 else ""
        value = rest[3] if len(rest) > 3 else ""
        if field in ("full_index_enabled", "audience_filter_enabled", "strategy_capability_view") and value in (
            "on",
            "off",
            "true",
            "false",
            "1",
            "0",
        ):
            flag = value in ("on", "true", "1")
            return sm.set_disclosure_policy(**{field: flag}, source="shell")
        if field == "full_index_limit" and value.isdigit():
            return sm.set_disclosure_policy(full_index_limit=int(value), source="shell")
        return {
            "success": False,
            "error": _t("shell.app_error.invalid_field_value", domain="disclosure", field=field, value=value),
            "suggestions": [
                "status",
                "set <full_index_enabled|audience_filter_enabled|strategy_capability_view> <on|off>",
                "set full_index_limit <number>",
            ],
        }
    return {
        "success": False,
        "error": _t("shell.app_error.unknown_action", domain="disclosure", action=action),
        "suggestions": ["status", "set <field> <value>"],
    }


def _skills_guidance(sm, rest: list[str]) -> dict:
    """Guidance operating-mode control (small | full)."""
    action = rest[1] if len(rest) > 1 else "status"
    if action == "status":
        return {"success": True, "policy": sm.guidance_policy()}
    if action == "set":
        mode = rest[2] if len(rest) > 2 else ""
        return sm.set_guidance_policy(mode=mode, source="shell")
    return {
        "success": False,
        "error": _t("shell.app_error.unknown_action", domain="guidance", action=action),
        "suggestions": ["status", "set <small|full>"],
    }


def _skills_evolve(sm, rest: list[str], role: str, agent_id: str) -> dict:
    """Evolve a new skill from an intent via the R4 agent (write gate enforced)."""
    intent = " ".join(rest[1:])
    if not intent:
        return {"success": False, "error": _t("shell.app_error.usage_skills_evolve")}
    # evolve persists a new skill to disk — honor the developer write gate
    # like create/update/delete/reload (see authorize_write in SkillManager).
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": _t("shell.app_error.permission_denied", who=who)}
    try:
        from l3.memory.r4_agent import get_r4_agent

        return get_r4_agent().evolve_skill(intent)
    except Exception as e:
        return {"success": False, "error": _t("shell.app_error.evolve_failed", error=e)}


def _skills_create(sm, rest: list[str], role: str, agent_id: str) -> dict:
    """Create a skill (developer-only)."""
    if len(rest) < 4:
        return {"success": False, "error": _t("shell.app_error.usage_skills_create")}
    name, desc, prompt = rest[1], rest[2], rest[3]
    return sm.create(name, description=desc, prompt=prompt, agent_id=agent_id, role=role)


def _skills_update(sm, rest: list[str], role: str, agent_id: str) -> dict:
    """Update a skill field (developer-only)."""
    if len(rest) < 4:
        return {"success": False, "error": _t("shell.app_error.usage_skills_update")}
    name, field, value = rest[1], rest[2], rest[3]
    if field not in ("description", "prompt", "rules"):
        return {"success": False, "error": _t("shell.app_error.unsupported_field", field=field)}
    data: dict[str, object] = {"rules": [r for r in value.split(";") if r]} if field == "rules" else {field: value}
    return sm.update(name, data, agent_id=agent_id, role=role)


def _skills_delete(sm, rest: list[str], role: str, agent_id: str) -> dict:
    """Delete a skill (developer-only)."""
    name = rest[1] if len(rest) > 1 else ""
    if not name:
        return {"success": False, "error": _t("shell.app_error.usage_skills_delete")}
    return sm.delete(name, agent_id=agent_id, role=role)


# 8-tuple success shape: (name, desc, prompt, scope, scope_identity, priority, tags, tools)
_RegisterParse = tuple[str, str, str, str, str, int, list[str], list[str] | None]


def _parse_register_args(rest: list[str]) -> tuple[_RegisterParse | None, str | None]:
    """Parse /skills register CLI args.

    Returns (None, error_message) on usage error, or (8-tuple, None) on
    success — an explicit pair so callers can narrow without mypy losing
    the tuple shape.
    """
    if len(rest) < 4:
        return None, _t("shell.app_error.usage_skills_register")
    prompt_parts: list[str] = []
    scope = ""
    scope_identity = ""
    priority = 0
    tags: list[str] = []
    tools: list[str] | None = None
    args = rest[3:]
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--scope" and idx + 1 < len(args):
            scope = args[idx + 1]
            idx += 2
        elif arg == "--identity" and idx + 1 < len(args):
            scope_identity = args[idx + 1]
            idx += 2
        elif arg == "--priority" and idx + 1 < len(args):
            try:
                priority = int(args[idx + 1])
            except ValueError:
                return None, "priority must be an integer"
            idx += 2
        elif arg == "--tags" and idx + 1 < len(args):
            tags = [t.strip() for t in args[idx + 1].split(",") if t.strip()]
            idx += 2
        elif arg == "--tools" and idx + 1 < len(args):
            tools = [t.strip() for t in args[idx + 1].split(",") if t.strip()]
            idx += 2
        else:
            prompt_parts.append(arg)
            idx += 1
    prompt = " ".join(prompt_parts)
    if not prompt:
        return None, "prompt is required"
    return (rest[1], rest[2], prompt, scope, scope_identity, priority, tags, tools), None


def _skills_register(sm, rest: list[str], role: str, agent_id: str) -> dict:
    """Register a user-authored custom skill (third tier, developer-only).

    Usage:
      /skills register <name> <desc> <prompt> [--scope agent|cell|global]
                   [--identity <role|id>] [--priority <int>]
                   [--tags <a,b>] [--tools <t1,t2>]

    Registration persists the skill into the custom tier (survives
    restart), tags it ``custom`` (TTL prune / curation leave it alone),
    and links it to related skill domains via the R5 graph (graceful when
    the graph is off).
    """
    parsed, parse_err = _parse_register_args(rest)
    if parsed is None:
        return {"success": False, "error": parse_err or _t("shell.app_error.usage_skills_register")}
    name, desc, prompt, scope, scope_identity, priority, tags, tools = parsed
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": _t("shell.app_error.permission_denied", who=who)}
    try:
        from l3.memory.r4_agent import get_r4_agent

        result = get_r4_agent().register_custom_skill(
            name=name,
            description=desc,
            prompt=prompt,
            tags=tags,
            allowed_tools=tools,
            scope=scope,
            scope_identity=scope_identity,
            priority=priority,
            agent_id=agent_id,
            role=role,
        )
    except Exception:
        # Fallback: in-memory registration only (persist is best-effort).
        result = sm.create(
            name,
            description=desc,
            prompt=prompt,
            tags=tags,
            allowed_tools=tools,
            scope=scope,
            scope_identity=scope_identity,
            priority=priority,
            agent_id=agent_id,
            role=role,
        )
        return _link_registered_skill(sm, name, scope, tags, result)
    if not result.get("success"):
        return result
    return {
        "success": True,
        "skill": name,
        "scope": scope,
        "persisted": result.get("persisted", True),
        "linked": result.get("linked", 0),
        "authorized": who,
    }


def _link_registered_skill(sm, name: str, scope: str, tags: list[str], result: dict) -> dict:
    """Register-time R5 linkage via the L3 entry point (layer-import safe).

    Delegates to ``l3.memory.r4_skill_retrieval.link_registered_skill_graph``
    so L2 never imports the memory graph directly. Degrades to a no-op when
    the graph is disabled — registration never hard-fails on linkage."""
    try:
        from l3.memory.r4_skill_retrieval import link_registered_skill_graph

        linked = link_registered_skill_graph(sm, name, scope, tags)
        return {"success": True, "skill": name, "scope": scope, "linked": linked.get("linked", 0), **result}
    except Exception:
        return {"success": True, "skill": name, "scope": scope, "linked": 0, **result}


def _skills_enable(sm, rest: list[str], role: str, agent_id: str) -> dict:
    """Enable a registered custom skill without deleting its file."""
    name = rest[1] if len(rest) > 1 else ""
    if not name:
        return {"success": False, "error": _t("shell.app_error.usage_skills_enable")}
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": _t("shell.app_error.permission_denied", who=who)}
    data = {"status": "active"}
    updated = sm.update(name, data, agent_id=agent_id, role=role)
    if not updated.get("success"):
        return updated
    return {"success": True, "skill": name, "enabled": True, "authorized": who}


def _skills_disable(sm, rest: list[str], role: str, agent_id: str) -> dict:
    """Disable a registered custom skill (keeps the file; stops injection)."""
    name = rest[1] if len(rest) > 1 else ""
    if not name:
        return {"success": False, "error": _t("shell.app_error.usage_skills_disable")}
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": _t("shell.app_error.permission_denied", who=who)}
    data = {"status": "retired"}
    updated = sm.update(name, data, agent_id=agent_id, role=role)
    if not updated.get("success"):
        return updated
    return {"success": True, "skill": name, "enabled": False, "authorized": who}


def _skills_update_speed(sm, rest: list[str], role: str, agent_id: str) -> dict:
    """Adjust the R4Agent skill-update cadence (fast|slow, on|off)."""
    if len(rest) < 2:
        return {"success": False, "error": _t("shell.app_error.usage_skills_update_speed")}
    speed = rest[1]
    enabled: bool | None = None
    if len(rest) > 2:
        flag = rest[2].lower()
        if flag in ("on", "enable"):
            enabled = True
        elif flag in ("off", "disable"):
            enabled = False
        else:
            return {"success": False, "error": _t("shell.app_error.usage_update_speed_flag", flag=flag)}
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": _t("shell.app_error.permission_denied", who=who)}
    return sm.set_update_policy(update_speed=speed, enabled=enabled, source="shell")


def _skills_reload(sm, rest: list[str], role: str, agent_id: str) -> dict:
    """Reload builtin skills (developer-only)."""
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": _t("shell.app_error.permission_denied", who=who)}
    count = sm.load_builtin()
    return {"success": True, "loaded": count, "authorized": who}


_SKILL_HANDLERS: dict[str, Callable[..., dict]] = {
    "list": lambda sm, rest, role, agent_id: _skills_list(sm, rest),
    "ls": lambda sm, rest, role, agent_id: _skills_list(sm, rest),
    "lean": lambda sm, rest, role, agent_id: _skills_lean(sm, rest),
    "get": lambda sm, rest, role, agent_id: _skills_get(sm, rest),
    "permissions": lambda sm, rest, role, agent_id: _skills_permissions(sm, rest),
    "distill": lambda sm, rest, role, agent_id: _skills_distill(sm, rest),
    "candidate": _skills_candidates,
    "candidates": _skills_candidates,
    "retriever": lambda sm, rest, role, agent_id: _skills_retriever(sm, rest),
    "pipeline": lambda sm, rest, role, agent_id: _skills_pipeline(sm, rest),
    "disclosure": lambda sm, rest, role, agent_id: _skills_disclosure(sm, rest),
    "guidance": lambda sm, rest, role, agent_id: _skills_guidance(sm, rest),
    "evolve": _skills_evolve,
    "create": _skills_create,
    "update": _skills_update,
    "delete": _skills_delete,
    "register": _skills_register,
    "enable": _skills_enable,
    "disable": _skills_disable,
    "update-speed": _skills_update_speed,
    "reload": _skills_reload,
}


def _cmd_skills(args: list[str], session=None) -> dict:
    """Manage skills — list/get are public; create/update/delete/reload are developer-only.

    Usage:
      /skills                          → list skills
      /skills list                     → list skills
      /skills lean                     → list lean case skills
      /skills get <name>               → skill detail
      /skills create <name> <desc> <prompt> [--role <role>]
      /skills update <name> <field> <value> [--role <role>]
      /skills delete <name> [--role <role>]
      /skills reload [--role <role>]
      /skills evolve <intent>          → generate a new skill via LLM
      /skills permissions              → current write-gate policy
      /skills distill [status]        → distillation/DPO master + sub switches
      /skills distill set <field> <on|off>  → toggle distill|dpo_signal|generalize|llm_distill|clustering|sampling
      /skills retriever [status]       → active retrieval backend (tfidf|embedding)
      /skills retriever set <backend>  → switch retrieval backend at runtime
      /skills pipeline [status]        → retrieval/curation pipeline policy + thresholds
      /skills pipeline set <field> <value> → toggle retrieval|curation, tune contrib_min_trials|contrib_min_ratio|retrieval_min_score
      /skills disclosure [status]      → progressive-disclosure policy (index/audience/capability)
      /skills disclosure set <field> <value> → toggle full_index_enabled|audience_filter_enabled|strategy_capability_view, set full_index_limit
      /skills guidance [status]        → guidance operating mode (small|full)
      /skills guidance set <mode>      → switch small|full (small = fields inert)

    The optional ``--role``/``--agent`` flag supplies the caller identity for
    the SkillManager developer gate; omitting it treats the call as a
    system-internal (boot/CLI) operation.
    """
    from l1.kernel.skill import get_skill_manager

    sm = get_skill_manager()

    role, agent_id, rest = _parse_skill_args(args)
    sub = rest[0] if rest else "list"

    handler = _SKILL_HANDLERS.get(sub)
    if not handler:
        return {
            "success": False,
            "error": _t("shell.app_error.unknown_skills_subcommand", sub=sub),
            "suggestions": ["list", "get", "create", "update", "delete", "reload", "permissions"],
        }
    return handler(sm, rest, role, agent_id)


def _cmd_process(args: list[str], session=None) -> dict:
    from l1.kernel.process import get_table

    if args and args[0] == "audit":
        return {"success": True, "audit": get_table().audit_log()}
    return {"success": True, "processes": get_table().list_processes()}


def _cmd_vfs(args: list[str], session=None) -> dict:
    from l1.kernel.vfs import get_vfs

    path = args[0] if args else "/"
    r = get_vfs().read(path)
    if r.get("success"):
        print(r["content"])
    return r


def _cmd_cache(args: list[str], session=None) -> dict:
    from l1.kernel.params.agent import DEFAULT_CELL_ID
    from l3.cell import get_cell

    cell = get_cell(DEFAULT_CELL_ID)
    return {"success": True, "cache": cell.cache.stats() if hasattr(cell, "cache") else {}}


def _cmd_sysinfo(args: list[str], session=None) -> dict:
    import sys

    return {"success": True, "python": sys.version, "platform": sys.platform}


def _cmd_clear(args: list[str], session=None) -> dict:
    print("\033[2J\033[H", end="")
    return {"success": True, "clear": True}


def _cmd_history(args: list[str], session=None) -> dict:
    from l1.kernel.params.system import SHELL_HISTORY_DEFAULT_LIMIT

    limit = int(args[0]) if args and args[0].isdigit() else SHELL_HISTORY_DEFAULT_LIMIT
    return {"success": True, "history": [], "limit": limit}


def _cmd_lang(args: list[str], session=None) -> dict:
    from l2.i18n import get_available_locales, get_locale, set_locale

    if args:
        set_locale(args[0])
    return {"success": True, "locale": get_locale(), "available": get_available_locales()}


def _cmd_devices(args: list[str], session=None) -> dict:
    from l1.kernel.device import get_device_manager

    dm = get_device_manager()
    devices = dm.list()
    return {"success": True, "devices": devices, "count": len(devices)}


def _cmd_tools(args: list[str], session=None) -> dict:
    from l3.agent_terminal import get_terminals

    agent_id = args[0] if args else ""
    terms = get_terminals()
    if agent_id:
        term = terms.get(agent_id)
        if not term:
            return {"success": False, "error": _t("shell.app_error.unknown_agent", agent_id=agent_id)}
        tools = term.list_tools()
        return {"success": True, "tools": tools, "agent": agent_id}
    return {"terminals": list(terms.keys())}


def _cmd_help(args: list[str], session=None) -> dict:
    """Show help for commands (/help <cmd>) or list all commands."""
    from l1.kernel.commands import get_command
    from l2.l2_shell.commands import list_commands

    if args:
        cmd_name = args[0].lower().lstrip("/")
        cmd = get_command(cmd_name)
        if not cmd:
            return {"success": False, "error": _t("shell.app_error.unknown_command", cmd_name=cmd_name)}
        lines = [f"/{cmd_name}  — {cmd.get('help', '')}"]
        if cmd.get("aliases"):
            lines.append(f"  aliases: {', '.join('/' + a for a in cmd['aliases'])}")
        if cmd.get("args"):
            lines.append("  args:")
            for a in cmd["args"]:
                opt = " (optional)" if a.get("optional") else ""
                lines.append(f"    {a['name']}{opt} — {a.get('description', '')}")
        if cmd.get("examples"):
            lines.append("  examples:")
            for e in cmd["examples"]:
                lines.append(f"    {e}")
        lines.append(f"  category: {cmd.get('category', 'other')}")
        return {"success": True, "output": "\n".join(lines), "format": "table"}
    cmds = list_commands()
    groups: dict[str, list] = {}
    for c in cmds:
        cat = c.get("category", "other")
        groups.setdefault(cat, []).append(c)
    cat_labels = {
        "session": _t("shell.render.cat_session"),
        "control": _t("shell.render.cat_control"),
        "memory": _t("shell.render.cat_memory"),
        "system": _t("shell.render.cat_system"),
        "agent": _t("shell.render.cat_agent"),
        "audit": _t("shell.render.cat_audit"),
        "ext": _t("shell.render.cat_ext"),
    }
    lines = [_t("shell.render.available"), ""]
    for cat in ["session", "control", "memory", "system", "agent", "audit", "ext"]:
        items = groups.get(cat, [])
        if not items:
            continue
        label = cat_labels.get(cat, cat)
        lines.append(f"  ── {label} ──")
        for c in items:
            name = c.get("command", "")
            help_text = c.get("help", "")
            alias_str = ""
            if c.get("aliases"):
                alias_str = f" ({', '.join('/' + a for a in c['aliases'])})"
            lines.append(f"    {name:25s} {help_text}{alias_str}")
        lines.append("")
    lines.append("  Tip: /help <command> for details & examples")
    lines.append("  Tip: cmd1 | cmd2 for pipeline (auto Map/Chain/Passthrough)")
    lines.append("  Tip: --cell or --agent for scoped operations")
    return {"success": True, "output": "\n".join(lines), "format": "table"}
