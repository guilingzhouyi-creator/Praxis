"""L2 Shell: memory and agent control commands (audit, card, memory, spawn, kill, plugins, tokens)."""

from __future__ import annotations

import logging

from l1.kernel.params.agent import DEFAULT_CELL_ID
from l2.i18n import t as _t
from l3.error_bus import capture

logger = logging.getLogger(__name__)


def _cmd_memory_filter(args: list[str]) -> dict:
    """/memory filter [on|off] [fine|coarse] — memory domain-filter switches.

    Without args: report current switch state. ``on``/``off`` flips the
    master switch; ``fine``/``coarse`` flips the fine-grained switch.
    """
    from l3.memory.memory_domain_filter import get_memory_filter

    f = get_memory_filter()
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


def _cmd_memory(args: list[str]) -> dict:
    from .common import resolve_agents, resolve_scope

    scope, scope_id, rest = resolve_scope(args)
    op = rest[0].lower() if rest else "search"
    # Phase 3 M4: /memory corpus [limit] — export the correction corpus
    # (refined memory + identity/domain context + log snapshots) for
    # external training tooling. Global op: does not need agent resolution.
    if op == "corpus":
        from l3.memory.memory_record_source import export_corpus

        limit = int(rest[1]) if len(rest) >= 2 and str(rest[1]).isdigit() else 0
        return export_corpus(limit=limit)
    # Phase 3.1 B1: /memory digest [on|off] [max_chars=N] — conversation
    # digest-cache operator switches (card-indexed folded-span summary
    # buffer). Global op: does not need agent resolution.
    if op == "digest":
        from l3.agent.digest_cache import digest_status, set_digest_switches

        sub = rest[1].lower() if len(rest) >= 2 else ""
        if sub in ("on", "off"):
            return set_digest_switches(enabled=sub == "on")
        for arg in rest[1:]:
            if arg.startswith("max_chars=") and arg[10:].isdigit():
                return set_digest_switches(max_chars=int(arg[10:]))
        return digest_status()
    # Phase 3.1 B2: /memory tool-result [on|off] [max_chars=N] — structured
    # per-Cell offload of oversized tool results. Global op.
    if op == "tool-result":
        from l3.agent.tool_result_cache import set_tool_result_switches, tool_result_status

        sub = rest[1].lower() if len(rest) >= 2 else ""
        if sub in ("on", "off"):
            return set_tool_result_switches(enabled=sub == "on")
        for arg in rest[1:]:
            if arg.startswith("max_chars=") and arg[10:].isdigit():
                return set_tool_result_switches(max_chars=int(arg[10:]))
        return tool_result_status()
    # Execution-layer context audit: /memory context-audit [cell_id] —
    # per-agent context pressure across a Cell (management surface for
    # context isolation). Global op.
    if op == "context-audit":
        from l3.agent.agent_loop import audit_cell_context

        cell_id = rest[1] if len(rest) >= 2 else ""
        return audit_cell_context(cell_id=cell_id)
    # System-prompt versioning: /memory prompt-version [snapshot|
    # rollback=key@version] — revision tracking + rollback for the prompt
    # library (3.2). Global op.
    if op == "prompt-version":
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
    # System-prompt bypass monitor: /memory prompt-monitor [on|off|stats|
    # emit] — usage/success/failure analytics (3.2, default off = prod).
    if op == "prompt-monitor":
        from l3.agent.prompt_monitor import (
            emit_prompt_metrics,
            prompt_monitor_stats,
            prompt_monitor_status,
            set_prompt_monitor,
        )

        sub = rest[1].lower() if len(rest) >= 2 else ""
        if sub in ("on", "off"):
            return set_prompt_monitor(enabled=sub == "on")
        if sub == "stats":
            return {"status": prompt_monitor_status(), **prompt_monitor_stats()}
        if sub == "emit":
            return emit_prompt_metrics()
        return {"status": prompt_monitor_status(), **prompt_monitor_stats()}
    # Prompt-library switches: /memory prompt-library [on|off] [global=on|
    # off] — Cell + global shared prompt libraries (3.2, default ON).
    if op == "prompt-library":
        from l3.agent.global_prompt_library import (
            global_prompt_library_status,
            set_global_prompt_library_switches,
        )
        from l3.agent.prompt_library import prompt_library_status, set_prompt_library_switches

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
    # Phase 3.1 B6: /memory sensitive [on|off] — bypass sensitive-info
    # detection on the compression path (default ON). Global op.
    if op == "sensitive":
        from l3.agent.sensitive_detect import sensitive_status, set_sensitive_switches

        sub = rest[1].lower() if len(rest) >= 2 else ""
        if sub in ("on", "off"):
            return set_sensitive_switches(enabled=sub == "on")
        return sensitive_status()
    # Phase 3.1 B6: /memory compression-guard [threshold=N] [breaker=on|off]
    # — recursive-compression threshold (default 0 = off) + circuit breaker
    # (default on). Setting a threshold resets a tripped breaker. Global op.
    if op == "compression-guard":
        from l3.agent.compression_guard import guard_status, set_guard_switches

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
    for aid in agents:
        try:
            from l3.memory.memory import get_memory

            mem = get_memory()
            if op == "search":
                r = mem.recall(agent_id=aid, query=kwargs.get("query", ""), limit=10)
            elif op == "stats":
                r = mem.aggregate_stats(agent_id=aid)
            else:
                return {"success": False, "error": f"unknown memory op: {op}"}
            return {"success": True, "agent": aid, "data": r}
        except Exception as e:
            capture("memory: cmd failed", error_code="E_CMD", component="l2", context={"error": str(e)})
            return {"success": False, "error": str(e)}
    return {"success": True}


def _cmd_card(args: list[str]) -> dict:
    from l3.card.card_registry import get_registry

    cr = get_registry()
    if not args:
        return {"success": True, "data": {"cards": cr.list(state=None)[:10]}}
    sub = args[0].lower()
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


def _cmd_plugins(args: list[str]) -> dict:
    from l3.services.central_plugin import get_center

    center = get_center()
    if args and args[0] == "stats":
        return {"success": True, "stats": center.stats() if hasattr(center, "stats") else {}}
    return {"success": True, "plugins": center.list_plugins() if hasattr(center, "list_plugins") else []}


def _cmd_spawn(args: list[str]) -> dict:
    from l1.kernel.params.agent import CENTRAL_DEFAULT_ROLES
    from l3.cell import get_cell

    if not args:
        return {"success": False, "error": _t("shell.app_error.usage_spawn")}
    name, role = args[0], args[1] if len(args) > 1 else CENTRAL_DEFAULT_ROLES[0]
    cell = get_cell(DEFAULT_CELL_ID)
    return cell.add_agent(name, role=role)


def _cmd_kill(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": _t("shell.app_error.usage_kill")}
    from l3.agent_terminal import get_terminals

    terms = get_terminals()
    if args[0] in terms:
        terms[args[0]].shutdown()
    return {"success": True}


def _cmd_destroy(args: list[str]) -> dict:
    from l3.cell import reset_cells

    reset_cells()
    return {"success": True, "message": _t("shell.render.cells_reset")}


def _cmd_emergency(args: list[str]) -> dict:
    from l3.cell import get_cell

    cell = get_cell(DEFAULT_CELL_ID)
    return cell.emergency_stop()


def _cmd_audit(args: list[str]) -> dict:
    from l1.kernel import get_audit_log

    limit = int(args[0]) if args and args[0].isdigit() else 20
    return {"success": True, "audit": get_audit_log(limit=limit)}


def _cmd_cell_create(args: list[str]) -> dict:
    from l3.cell import get_cell

    cell_id = args[0] if args else "cell-new"
    get_cell(cell_id, [args[1] if len(args) > 1 else "."])
    return {"success": True, "cell_id": cell_id}


def _cmd_agent_restart(args: list[str]) -> dict:
    from l3.cell import get_cell

    if not args:
        return {"success": False, "error": _t("shell.app_error.usage_agent_restart")}
    cell = get_cell(DEFAULT_CELL_ID)
    return cell.restart_agent(args[0])


def _cmd_agent_refresh(args: list[str]) -> dict:
    from l3.cell import get_cell

    cell = get_cell(DEFAULT_CELL_ID)
    if args:
        return cell.reset_agent_context(args[0])
    return {"success": False, "error": _t("shell.app_error.agent_id_required")}


def _cmd_tokens(args: list[str]) -> dict:
    from l1.kernel.allocator import get_allocator

    alloc = get_allocator()
    if args:
        return alloc.usage(args[0])
    return alloc.summary()
