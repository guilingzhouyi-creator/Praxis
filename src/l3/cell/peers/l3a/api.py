"""L2 Shell API — command routing for `/l3a`."""

from __future__ import annotations

from . import archive as _archive
from . import params as _p
from .context import ContextRegistry
from .model import L3AModelConfig
from .session import SessionManager


def _dispatch_agents_md(args: list[str]) -> dict:
    """Generic project-handbook pipeline (collect → assemble → sandbox write → generalize)."""
    from .agents_md import generate_agents_md

    evolve = not (len(args) > 1 and args[1].lower() in ("--no-evolve", "-n"))
    return generate_agents_md(agent_id="l3a", evolve=evolve)


def _dispatch_create(
    args: list[str], mgr: SessionManager, registry: ContextRegistry, model_cfg: L3AModelConfig
) -> dict:
    """Create a new L3A session."""
    title = " ".join(args[1:]) if len(args) > 1 else ""
    created = mgr.create(title=title, model_config=model_cfg, registry=registry)
    return {"success": True, "data": created.info()}


def _dispatch_resume(
    args: list[str], mgr: SessionManager, registry: ContextRegistry, model_cfg: L3AModelConfig
) -> dict:
    """Resume an archived session by id."""
    if len(args) < 2:
        return {"success": False, "error": "archived session_id required"}
    from .session import Session

    s = Session.resume_from_archive(args[1], model_config=model_cfg, registry=registry)
    if not s:
        return {"success": False, "error": f"archived session not found: {args[1]}"}
    with mgr._lock:
        mgr._sessions[s.id] = s
    return {"success": True, "data": s.info(), "resumed_from": args[1]}


def _dispatch_list(mgr: SessionManager) -> dict:
    """List active + archived sessions."""
    active = mgr.list_active()
    arch = _archive.search_sessions(limit=_p.DEFAULT_SEARCH_LIMIT)
    return {
        "success": True,
        "data": {
            "active": active,
            "archived": arch.get("data", []),
        },
        "count": len(active) + len(arch.get("data", [])),
    }


def _dispatch_info(args: list[str], mgr: SessionManager) -> dict:
    """Show session info (active first, then archived)."""
    sid = args[1] if len(args) > 1 else ""
    if sid:
        s = mgr.get(sid)
        if s:
            return {"success": True, "data": s.info()}
        r = _archive.search_sessions(session_id=sid)
        if r["count"]:
            return {"success": True, "data": r["data"][0]}
        return {"success": False, "error": f"session not found: {sid}"}
    return {"success": False, "error": "session_id required"}


def _dispatch_close(args: list[str], mgr: SessionManager) -> dict:
    """Close an active session."""
    sid = args[1] if len(args) > 1 else ""
    if sid:
        return mgr.close(sid)
    return {"success": False, "error": "session_id required"}


def _dispatch_messages(args: list[str], mgr: SessionManager) -> dict:
    """Page through a session's message history."""
    if len(args) < 2:
        return {"success": False, "error": "session_id required"}
    sid = args[1]
    s = mgr.get(sid)
    if not s:
        return {"success": False, "error": f"session not active: {sid}"}
    limit = int(args[2]) if len(args) > 2 and args[2].isdigit() else 20
    page = s.messages(limit=limit)
    return {
        "success": True,
        "data": page.items,
        "cursor": page.cursor,
        "total": page.total,
        "count": len(page.items),
    }


def _dispatch_tasks(args: list[str], mgr: SessionManager) -> dict:
    """List a session's tasks, optionally filtered by status."""
    if len(args) < 2:
        return {"success": False, "error": "session_id required"}
    sid = args[1]
    s = mgr.get(sid)
    if not s:
        return {"success": False, "error": f"session not active: {sid}"}
    status = args[2] if len(args) > 2 else ""
    return {
        "success": True,
        "session_id": sid,
        "data": s.tasks.list_tasks(status=status),
        "pending": s.tasks.pending_count(),
        "count": len(s.tasks.all()),
    }


def _dispatch_todos(args: list[str], mgr: SessionManager) -> dict:
    """Show or update a session's todos."""
    if len(args) < 2:
        return {"success": False, "error": "session_id required"}
    sid = args[1]
    s = mgr.get(sid)
    if not s:
        return {"success": False, "error": f"session not active: {sid}"}
    if len(args) >= 4 and args[2].lower() == "update":
        return s.todos_update(args[3], args[4] if len(args) > 4 else "in_progress")
    return {"success": True, "session_id": sid, "data": s.todos()}


def _dispatch_convergence(args: list[str]) -> dict:
    """Show the convergence queue for a cell or all cells."""
    if len(args) >= 2:
        from .helpers import get_convergence_queue

        items = get_convergence_queue(args[1])
        return {"success": True, "cell_id": args[1], "data": items, "count": len(items)}
    from .daemon import _convergence_loader

    items = _convergence_loader()
    return {"success": True, "scope": "all", "data": items, "count": len(items)}


def _dispatch_convention(args: list[str]) -> dict:
    """Run the cross-cell convention handler for an issue."""
    if len(args) < 2:
        return {"success": False, "error": "issue_id required"}
    from .helpers import l3a_convention_handler

    return l3a_convention_handler(
        {
            "issue_id": args[1],
            "max_chars": int(args[2]) if len(args) > 2 and args[2].isdigit() else 0,
        }
    )


def _dispatch_summaries(args: list[str]) -> dict:
    """Show issue summaries (get / search / latest)."""
    from .helpers import l3a_summary_handler

    if len(args) >= 3 and args[1].lower() == "get":
        return l3a_summary_handler({"action": "get", "issue_id": args[2]})
    if len(args) >= 3 and args[1].lower() == "search":
        return l3a_summary_handler({"action": "search", "query": " ".join(args[2:])})
    domain = args[1] if len(args) >= 2 else ""
    return l3a_summary_handler({"action": "latest", "domain": domain, "limit": 10})


def _dispatch_compress(args: list[str], mgr: SessionManager) -> dict:
    """Compress a session, keeping the last N messages."""
    if len(args) < 2:
        return {"success": False, "error": "session_id required"}
    sid = args[1]
    s = mgr.get(sid)
    if not s:
        return {"success": False, "error": f"session not active: {sid}"}
    keep = int(args[2]) if len(args) > 2 and args[2].isdigit() else 10
    return s.compress(keep_last=keep)


def _dispatch_memory(args: list[str], mgr: SessionManager) -> dict:
    """Show memory usage for a session or the central monitor."""
    if len(args) >= 2:
        sid = args[1]
        s = mgr.get(sid)
        if not s:
            return {"success": False, "error": f"session not active: {sid}"}
        window = float(args[2]) if len(args) > 2 else 3600.0
        return s.memory_usage(window=window)
    from l3.memory.central_memory import get_center

    m = get_center().monitor()
    return {"success": True, "data": m}


def _dispatch_compress_status(mgr: SessionManager) -> dict:
    """Show auto-compress policy + live pressure across active sessions."""
    from l3.config.settings_center import get_center

    sc = get_center()
    policy = {
        "enabled": bool(sc.get("l3a.auto_compress", True)),
        "threshold": float(sc.get("l3a.auto_compress_threshold", 0.6)),
        "keep_last": int(sc.get("l3a.auto_compress_keep", 10)),
    }
    # live pressure for all active sessions
    live = []
    for info in mgr.list_active():
        sess = mgr.get(info.get("session_id", ""))
        if sess:
            try:
                cs = sess.context_stats()
                live.append(
                    {
                        "session_id": info["session_id"],
                        "pressure": cs.get("pressure_ratio", 0),
                        "level": cs.get("pressure_level", "ok"),
                        "history": sess.history.count(),
                    }
                )
            except Exception:
                continue
    return {"success": True, "policy": policy, "live": live}


def _dispatch_compress_force(args: list[str], mgr: SessionManager) -> dict:
    """Force the auto-compress check for a session."""
    if len(args) < 2:
        return {"success": False, "error": "session_id required"}
    sid = args[1]
    s = mgr.get(sid)
    if not s:
        return {"success": False, "error": f"session not active: {sid}"}
    return s.auto_compress_check(force=True)


def _dispatch_ask(args: list[str], mgr: SessionManager) -> dict:
    """Show a session's pending ask status."""
    if len(args) < 2:
        return {"success": False, "error": "session_id required"}
    sid = args[1]
    s = mgr.get(sid)
    if not s:
        return {"success": False, "error": f"session not active: {sid}"}
    return s.ask_status()


def _dispatch_ask_pending(args: list[str]) -> dict:
    """List pending questions for an agent (or all agents)."""
    from l3.tools._comm import pending_questions

    agent = args[1] if len(args) > 1 else ""
    items = pending_questions(agent)
    return {"success": True, "data": items, "count": len(items)}


def _dispatch_answer(args: list[str], mgr: SessionManager) -> dict:
    """Submit answers to a pending ask and resume the session."""
    if len(args) < 2:
        return {"success": False, "error": "session_id required"}
    sid = args[1]
    s = mgr.get(sid)
    if not s:
        return {"success": False, "error": f"session not active: {sid}"}
    answers: dict = {}
    free_form = ""
    for part in args[2:]:
        if "=" in part:
            k, _, v = part.partition("=")
            answers[k.strip()] = v.strip()
        else:
            free_form = (free_form + " " + part).strip()
    r = s.submit_answers(answers, free_form)
    if r.get("success"):
        return s.resume_after_ask()
    return r


def dispatch(args: list[str], mgr: SessionManager, registry: ContextRegistry, model_cfg: L3AModelConfig) -> dict:
    """Route `/l3a` shell subcommands to their handlers and return a result dict."""
    if not args:
        return {
            "success": True,
            "data": {
                "active_sessions": mgr.list_active(),
                "model": model_cfg.show(),
            },
        }

    sub = args[0].lower()

    if sub == "agents-md":
        return _dispatch_agents_md(args)
    if sub == "create":
        return _dispatch_create(args, mgr, registry, model_cfg)
    if sub == "resume":
        return _dispatch_resume(args, mgr, registry, model_cfg)
    if sub == "list":
        return _dispatch_list(mgr)
    if sub == "info":
        return _dispatch_info(args, mgr)
    if sub == "close":
        return _dispatch_close(args, mgr)
    if sub == "messages":
        return _dispatch_messages(args, mgr)
    if sub == "model":
        return _model_dispatch(args[1:], model_cfg)
    if sub == "context":
        return _context_dispatch(args[1:], registry)
    if sub == "tasks":
        return _dispatch_tasks(args, mgr)
    if sub == "todos":
        return _dispatch_todos(args, mgr)
    if sub == "convergence":
        return _dispatch_convergence(args)
    if sub == "convention":
        return _dispatch_convention(args)
    if sub == "summaries":
        return _dispatch_summaries(args)
    if sub == "compress":
        return _dispatch_compress(args, mgr)
    if sub == "memory":
        return _dispatch_memory(args, mgr)
    if sub == "compress-status":
        return _dispatch_compress_status(mgr)
    if sub == "compress-force":
        return _dispatch_compress_force(args, mgr)
    if sub == "ask":
        return _dispatch_ask(args, mgr)
    if sub == "ask-pending":
        return _dispatch_ask_pending(args)
    if sub == "answer":
        return _dispatch_answer(args, mgr)

    return {"success": False, "error": f"unknown subcommand: {sub}"}


def _model_dispatch(args: list[str], cfg: L3AModelConfig) -> dict:
    if not args:
        return {"success": True, "data": cfg.show()}
    op = args[0].lower()
    if op == "show":
        return {"success": True, "data": cfg.show()}
    if op == "set" and len(args) >= 3:
        cfg.set(args[1], args[2])
        return {"success": True, "data": cfg.show()}
    return {"success": False, "error": "usage: model show|set <key> <value>"}


def _context_dispatch(args: list[str], registry: ContextRegistry) -> dict:
    if not args:
        return {
            "success": True,
            "data": {
                "sources": registry.list_sources(),
            },
        }
    op = args[0].lower()
    if op == "sources":
        return {"success": True, "data": registry.list_sources()}
    return {"success": False, "error": f"unknown context subcommand: {op}"}
