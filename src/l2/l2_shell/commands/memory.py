"""L2 Shell: memory and agent control commands (audit, card, memory, spawn, kill, plugins, tokens)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from l1.kernel.params.agent import DEFAULT_CELL_ID
from l2.bridge import capture
from l2.i18n import t as _t

logger = logging.getLogger(__name__)


def _cmd_memory_filter(args: list[str], session=None) -> dict:
    """/memory filter [on|off] [fine|coarse] — memory domain-filter switches.

    Without args: report current switch state. ``on``/``off`` flips the
    master switch; ``fine``/``coarse`` flips the fine-grained switch.
    """
    from l2.bridge import memory_filter

    f = memory_filter()
    if not args:
        return {"success": True, "filter": f.status()}
    enabled = None
    fine = None
    for a in args:
        al = a.lower()
        if al in ("on", "enable"):
            enabled = True
        elif al in ("off", "disable"):
            enabled = False
        elif al in ("fine", "fine-grained"):
            fine = True
        elif al in ("coarse",):
            fine = False
        else:
            return {"success": False, "error": _t("shell.app_error.invalid_arg").format(arg=a)}
    return {"success": True, "filter": f.set_switches(enabled=enabled, fine_grained=fine)}


def _memory_corpus(rest: list[str]) -> dict:
    """/memory corpus [limit] — export the correction corpus (global op)."""
    from l2.bridge import export_corpus

    limit = int(rest[1]) if len(rest) >= 2 and str(rest[1]).isdigit() else 0
    return export_corpus(limit=limit)


def _memory_digest(rest: list[str]) -> dict:
    """/memory digest [on|off] [max_chars=N] — digest-cache switches (global op)."""
    from l2.bridge import digest_status, set_digest_switches

    sub = rest[1].lower() if len(rest) >= 2 else ""
    if sub in ("on", "off"):
        return set_digest_switches(enabled=sub == "on")
    for arg in rest[1:]:
        if arg.startswith("max_chars=") and arg[10:].isdigit():
            return set_digest_switches(max_chars=int(arg[10:]))
    return digest_status()


def _memory_tool_result(rest: list[str]) -> dict:
    """/memory tool-result [on|off] [max_chars=N] — tool-result offload switches (global op)."""
    from l2.bridge import set_tool_result_switches, tool_result_status

    sub = rest[1].lower() if len(rest) >= 2 else ""
    if sub in ("on", "off"):
        return set_tool_result_switches(enabled=sub == "on")
    for arg in rest[1:]:
        if arg.startswith("max_chars=") and arg[10:].isdigit():
            return set_tool_result_switches(max_chars=int(arg[10:]))
    return tool_result_status()


def _memory_compaction(rest: list[str]) -> dict:
    """/memory compaction [deterministic|llm-assisted|off] — hybrid extractor mode (global op)."""
    from l2.bridge import compaction_status, set_compaction_mode

    sub = rest[1].lower() if len(rest) >= 2 else ""
    if sub in ("deterministic", "llm-assisted", "off"):
        return set_compaction_mode(sub)
    return compaction_status()


def _memory_premise_guard(rest: list[str]) -> dict:
    """/memory premise-guard [on|off] — post-compaction anchor audit (global op)."""
    from l2.bridge import premise_guard_status, set_premise_guard

    sub = rest[1].lower() if len(rest) >= 2 else ""
    if sub in ("on", "off"):
        return set_premise_guard(enabled=sub == "on")
    return premise_guard_status()


def _memory_inject_dedup(rest: list[str]) -> dict:
    """/memory inject-dedup [on|off] — injection content dedup (global op)."""
    from l2.bridge import inject_dedup_status, set_inject_dedup

    sub = rest[1].lower() if len(rest) >= 2 else ""
    if sub in ("on", "off"):
        return set_inject_dedup(enabled=sub == "on")
    return inject_dedup_status()


def _memory_context_audit(rest: list[str]) -> dict:
    """/memory context-audit [cell_id] — per-agent context pressure (global op)."""
    from l2.bridge import audit_cell_context

    cell_id = rest[1] if len(rest) >= 2 else ""
    return audit_cell_context(cell_id=cell_id)


def _memory_prompt_version(rest: list[str]) -> dict:
    """/memory prompt-version [snapshot|rollback=key@version] — prompt versioning (global op)."""
    from l1.kernel.prompts import prompt_versioning_status, prompt_versions, rollback_prompt

    sub = rest[1] if len(rest) >= 2 else ""
    if sub.startswith("rollback="):
        target = sub[len("rollback=") :]
        if "@" in target:
            key, ver = target.rsplit("@", 1)
            if ver.isdigit():
                return rollback_prompt(key, int(ver))
    if sub == "snapshot":
        return prompt_versions()
    return {"status": prompt_versioning_status(), **prompt_versions()}


def _memory_prompt_monitor(rest: list[str]) -> dict:
    """/memory prompt-monitor [on|off|stats|emit] — bypass monitor (global op)."""
    from l2.bridge import emit_prompt_metrics, prompt_monitor_stats, prompt_monitor_status, set_prompt_monitor

    sub = rest[1].lower() if len(rest) >= 2 else ""
    if sub in ("on", "off"):
        return set_prompt_monitor(enabled=sub == "on", source="shell")
    if sub == "stats":
        return {"status": prompt_monitor_status(), **prompt_monitor_stats()}
    if sub == "emit":
        return emit_prompt_metrics()
    return {"status": prompt_monitor_status(), **prompt_monitor_stats()}


def _memory_prompt_library(rest: list[str]) -> dict:
    """/memory prompt-library [on|off] [global=on|off] — shared prompt libraries (global op)."""
    from l2.bridge import (
        global_prompt_library_status,
        prompt_library_status,
        set_global_prompt_library_switches,
        set_prompt_library_switches,
    )

    cell = None
    glob = None
    for arg in rest[1:]:
        if arg.lower() in ("on", "off"):
            cell = arg.lower() == "on"
        elif arg.startswith("global=") and arg[7:] in ("on", "off"):
            glob = arg[7:] == "on"
    out = {}
    if cell is not None:
        out["cell"] = set_prompt_library_switches(enabled=cell)
    if glob is not None:
        out["global"] = set_global_prompt_library_switches(enabled=glob)
    return {"success": True, "cell": prompt_library_status(), "global": global_prompt_library_status(), **out}


def _memory_sensitive(rest: list[str]) -> dict:
    """/memory sensitive [on|off] [action=report|redact|block] — sensitive-info switch (global op)."""
    from l2.bridge import sensitive_status, set_sensitive_switches

    sub = rest[1].lower() if len(rest) >= 2 else ""
    enabled = None
    action = None
    if sub in ("on", "off"):
        enabled = sub == "on"
    for arg in rest[1:]:
        if arg.startswith("action=") and arg[7:] in ("report", "redact", "block"):
            action = arg[7:]
    if enabled is not None or action is not None:
        return set_sensitive_switches(enabled=enabled, action=action)
    return sensitive_status()


def _memory_compression_guard(rest: list[str]) -> dict:
    """/memory compression-guard [threshold=N] [breaker=on|off] — recursion guard (global op)."""
    from l2.bridge import guard_status, set_guard_switches

    threshold = None
    breaker = None
    for arg in rest[1:]:
        if arg.startswith("threshold=") and arg[10:].isdigit():
            threshold = int(arg[10:])
        elif arg.startswith("breaker=") and arg[8:] in ("on", "off"):
            breaker = arg[8:] == "on"
    if threshold is not None or breaker is not None:
        return set_guard_switches(recursion_threshold=threshold, breaker_enabled=breaker)
    return guard_status()


_MEMORY_GLOBAL_OPS: dict[str, Callable[[list[str]], dict]] = {
    "corpus": _memory_corpus,
    "digest": _memory_digest,
    "tool-result": _memory_tool_result,
    "context-audit": _memory_context_audit,
    "prompt-version": _memory_prompt_version,
    "prompt-monitor": _memory_prompt_monitor,
    "prompt-library": _memory_prompt_library,
    "sensitive": _memory_sensitive,
    "compression-guard": _memory_compression_guard,
    "compaction": _memory_compaction,
    "premise-guard": _memory_premise_guard,
    "inject-dedup": _memory_inject_dedup,
}


def _memory_agent_op(op: str, agents: list, kwargs: dict) -> dict:
    """Run a per-agent memory op (search/stats) over the resolved agents."""
    for aid in agents:
        try:
            from l2.bridge import memory as get_memory

            mem = get_memory()
            if op == "search":
                r = mem.recall(agent_id=aid, query=kwargs.get("query", ""), limit=10)
            elif op == "stats":
                r = mem.aggregate_stats(agent_id=aid)
            else:
                return {"success": False, "error": _t("shell.app_error.unknown_memory_op", op=op)}
            return {"success": True, "agent": aid, "data": r}
        except Exception as e:
            capture("memory: cmd failed", error_code="E_CMD", component="l2", context={"error": str(e)})
            return {"success": False, "error": str(e)}
    return {"success": True}


def _cmd_memory(args: list[str], session=None) -> dict:
    from .common import resolve_agents, resolve_scope

    scope, scope_id, rest = resolve_scope(args)
    op = rest[0].lower() if rest else "search"
    # Phase 3.1: global ops (corpus/digest/tool-result/context-audit/
    # prompt-version/prompt-monitor/prompt-library/sensitive/compression-guard)
    # do not need agent resolution — dispatch them directly.
    handler = _MEMORY_GLOBAL_OPS.get(op)
    if handler:
        return handler(rest)
    agents = resolve_agents(scope, scope_id)
    if not agents:
        return {"success": False, "error": _t("shell.app_error.no_agents_found")}
    kwargs: dict[str, object] = {"agent_ids": agents}
    if len(rest) >= 2:
        kwargs["query"] = " ".join(rest[1:])
    # Phase 3 M1: /memory filter [on|off] [fine|coarse] — memory domain
    # filter operator switches (never code-embedded auto-enable).
    if op == "filter":
        return _cmd_memory_filter(rest[1:])
    return _memory_agent_op(op, agents, kwargs)


def _card_dispatch(sub: str, args: list[str], cr) -> dict:
    """Dispatch a card subcommand to its registry operation."""
    if sub == "list":
        return {"success": True, "data": {"cards": cr.list(state=None)[:20]}}
    if sub == "submit" and len(args) >= 2:
        return cr.submit(" ".join(args[1:]), ".")
    if sub == "cancel" and len(args) >= 2:
        return {"success": cr.cancel(args[1])}
    if sub == "approve" and len(args) >= 2:
        return cr.approve(args[1])
    if sub == "reject" and len(args) >= 2:
        reason = " ".join(args[2:]) if len(args) > 2 else ""
        return cr.reject(args[1], reason=reason)
    return {
        "success": False,
        "error": _t("shell.app_error.usage_card"),
    }


def _cmd_card(args: list[str], session=None) -> dict:
    from l2.bridge import card_registry as get_registry

    cr = get_registry()
    if not args:
        return {"success": True, "data": {"cards": cr.list(state=None)[:10]}}
    return _card_dispatch(args[0].lower(), args, cr)


def _cmd_plugins(args: list[str], session=None) -> dict:
    from l2.bridge import plugin_center as get_center

    center = get_center()
    if args and args[0] == "stats":
        return {"success": True, "stats": center.stats() if hasattr(center, "stats") else {}}
    return {"success": True, "plugins": center.list_plugins() if hasattr(center, "list_plugins") else []}


def _cmd_spawn(args: list[str], session=None) -> dict:
    from l1.kernel.params.agent import CENTRAL_DEFAULT_ROLES
    from l2.bridge import cell as get_cell

    if not args:
        return {"success": False, "error": _t("shell.app_error.usage_spawn")}
    name, role = args[0], args[1] if len(args) > 1 else CENTRAL_DEFAULT_ROLES[0]
    cell = get_cell(DEFAULT_CELL_ID)
    return cell.add_agent(name, role=role)


def _cmd_kill(args: list[str], session=None) -> dict:
    if not args:
        return {"success": False, "error": _t("shell.app_error.usage_kill")}
    from l2.bridge import terminals as get_terminals

    terms = get_terminals()
    if args[0] in terms:
        terms[args[0]].shutdown()
    return {"success": True}


def _cmd_destroy(args: list[str], session=None) -> dict:
    from l2.bridge import reset_cells

    reset_cells()
    return {"success": True, "message": _t("shell.render.cells_reset")}


def _cmd_emergency(args: list[str], session=None) -> dict:
    from l2.bridge import cell as get_cell

    cell = get_cell(DEFAULT_CELL_ID)
    return cell.emergency_stop()


def _cmd_audit(args: list[str], session=None) -> dict:
    from l1.kernel import get_audit_log

    limit = int(args[0]) if args and args[0].isdigit() else 20
    return {"success": True, "audit": get_audit_log(limit=limit)}


def _cmd_cell_create(args: list[str], session=None) -> dict:
    from l2.bridge import cell as get_cell

    cell_id = args[0] if args else "cell-new"
    get_cell(cell_id, [args[1] if len(args) > 1 else "."])
    return {"success": True, "cell_id": cell_id}


def _cmd_agent_restart(args: list[str], session=None) -> dict:
    from l2.bridge import cell as get_cell

    if not args:
        return {"success": False, "error": _t("shell.app_error.usage_agent_restart")}
    cell = get_cell(DEFAULT_CELL_ID)
    return cell.restart_agent(args[0])


def _cmd_agent_refresh(args: list[str], session=None) -> dict:
    from l2.bridge import cell as get_cell

    cell = get_cell(DEFAULT_CELL_ID)
    if args:
        return cell.reset_agent_context(args[0])
    return {"success": False, "error": _t("shell.app_error.agent_id_required")}


def _cmd_tokens(args: list[str], session=None) -> dict:
    from l1.kernel.allocator import get_allocator

    alloc = get_allocator()
    if args:
        return alloc.usage(args[0])
    return alloc.summary()
