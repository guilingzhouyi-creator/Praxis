"""L2 Shell: L3A session management commands.

Routes `/l3a` to the L3A daemon dispatch.
"""

from __future__ import annotations

from l3.cell.peers.l3a import dispatch as _l3a_dispatch

_l3a_initialized = False


def _ensure() -> None:
    global _l3a_initialized
    if not _l3a_initialized:
        from l3.cell.peers.l3a import start

        start()
        _l3a_initialized = True


def _cmd_l3a(args: list[str]) -> dict:
    _ensure()
    return _l3a_dispatch(args)


def _cmd_agents_md(args: list[str]) -> dict:
    """Generate/refresh the project handbook (AGENTS.md) via the L3A pipeline.

    Thin shell command: routes ``agents-md`` into the L3A dispatch, which
    runs collect → assemble → sandbox write → (optional) generalize.
    ``--no-evolve`` skips the R4Agent skill distillation step.
    """
    _ensure()
    return _l3a_dispatch(["agents-md"] + args)


def _cmd_session_monitor(args: list[str]) -> dict:
    """Session monitor (3.3): /session monitor [on|off] — real-time status
    of every registered session entity (running status / resource /
    progress counters, dual identity). Default ON.

    Args:
        args: optional ``on`` / ``off`` to toggle the monitor switch.

    Returns:
        dict with the switch state and per-session states.
    """
    from l3.agent_terminal import (
        session_monitor,
        session_monitor_status,
        set_session_monitor,
    )

    sub = args[0].lower() if args else ""
    if sub in ("on", "off"):
        return set_session_monitor(enabled=sub == "on")
    return {"status": session_monitor_status(), **session_monitor()}


def _cmd_session_reload(args: list[str]) -> dict:
    """Session auto-reload (3.3): /session reload <agent_id> [reason=...]
    — full session reset on anomaly (distinct from interrupt resume).

    Args:
        args: ``<agent_id>`` (required) and optional ``reason=<text>``.

    Returns:
        dict with the reload outcome (or a no-op note).
    """
    from l3.agent_terminal import auto_reload_session

    if not args:
        return {"success": False, "error": "usage: /session reload <agent_id> [reason=...]"}
    agent_id = args[0]
    reason = ""
    for arg in args[1:]:
        if arg.startswith("reason="):
            reason = arg[len("reason=") :]
    return auto_reload_session(agent_id, reason=reason)


def _cmd_session_history(args: list[str]) -> dict:
    """Session history (3.3): /session history [on|off|limit=N] [session=<id>]
    — query session records (start/end/duration), toggle the module.

    Args:
        args: optional ``on`` / ``off`` / ``limit=N`` / ``session=<id>``.

    Returns:
        dict with the history switch state and matching records.
    """
    from l3.cell.peers.l3a.session_json import (
        history_status,
        query_session_history,
        set_history,
    )

    limit = 20
    session_id = ""
    for arg in args:
        if arg.lower() in ("on", "off"):
            return set_history(enabled=arg.lower() == "on")
        if arg.startswith("limit=") and arg[6:].isdigit():
            limit = int(arg[6:])
        elif arg.startswith("session="):
            session_id = arg[len("session=") :]
    return {"status": history_status(), **query_session_history(limit=limit, session_id=session_id)}


def _cmd_session_resume(args: list[str]) -> dict:
    """Session restore / resume (3.3, TUI): /session resume <session_id>
    [page=N] — load the conversation window for recall/reload via the
    dynamic loader (pagination + label-alternated dispatch + cache hits).

    Args:
        args: ``<session_id>`` (required) and optional ``page=N``.

    Returns:
        dict with the loaded window (or an error when the session is
        unknown / empty).
    """
    if not args:
        return {"success": False, "error": "usage: /session resume <session_id> [page=N]"}
    session_id = args[0]
    page = 0
    for arg in args[1:]:
        if arg.startswith("page=") and arg[5:].isdigit():
            page = int(arg[5:])
    from l3.cell.peers.l3a.session_loader import load_for_window

    return load_for_window(session_id, page=page, page_size=10)
