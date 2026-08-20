"""Agent config API handlers — query and update agent parameters at runtime.

Endpoints:
  GET  /api/v1/agents/config  — return current agent_role_map, priorities, clearance, defaults
  PUT  /api/v1/agents/config  — update agent_role_map, agent_priority, or clearance selectively
"""

from __future__ import annotations


def agent_list(body: dict | None = None) -> dict:
    """List all registered agents and their config."""
    from l1.kernel.params.agent import AGENT_CLEARANCE, DEFAULT_AGENT_CONFIGS

    agents = {}
    for role, clearance in AGENT_CLEARANCE.items():
        cfg = DEFAULT_AGENT_CONFIGS.get(role)
        agents[role] = {
            "ring": clearance,
            "max_scouts": cfg.max_scouts if cfg else 3,
        }
    return {"success": True, "agents": agents}


def agent_select(body: dict | None = None) -> dict:
    """Select an agent by ID (stub for backward compat)."""
    agent_id = (body or {}).get("agent_id", "")
    if not agent_id:
        from l1.kernel.params.agent import DEFAULT_AGENT_CONFIGS

        roles = list(DEFAULT_AGENT_CONFIGS.keys())
        return {"success": True, "agents": [{"agent_id": r, "role": r} for r in roles]}
    return {"success": True, "agent_id": agent_id}


def agent_select_by(body: dict | None = None) -> dict:
    """Select an agent by role/domain (stub for backward compat)."""
    role = (body or {}).get("role", "")
    if role:
        return {"success": True, "agent_id": role, "role": role}
    return {"success": True, "agents": [], "note": "no role specified"}


def agent_preconnect(body: dict | None = None) -> dict:
    """Pre-connect verification (stub)."""
    agent_id = (body or {}).get("agent_id", "")
    return {"success": True, "agent_id": agent_id, "allowed": True}


def agent_reachable(body: dict | None = None) -> dict:
    """Check if agent is reachable (stub)."""
    agent_id = (body or {}).get("agent_id", "")
    return {"success": True, "agent_id": agent_id, "reachable": True}


def agent_direct(body: dict | None = None) -> dict:
    """Start direct session (stub)."""
    return {"success": True, "session_id": ""}


def agent_direct_close(body: dict | None = None) -> dict:
    """Close direct session (stub)."""
    return {"success": True}


def agent_review_message(body: dict | None = None) -> dict:
    """Review message (stub)."""
    return {"success": True, "approved": True}


def _shell_dispatch(body: dict | None = None) -> dict:
    """Dispatch one shell input line through the L2 command engine.

    Two modes: protocol v1 envelopes (body carries ``kind``/``v``) are
    forwarded to the shared ProtocolHost and answered with
    ``{"envelopes": [...]}``; legacy ``{"text", "session"}`` dict requests
    keep the historic path. The host owns per-session ShellSession state,
    so web clients use the same session semantics as the TS bridge.
    """
    body = body or {}
    if "kind" in body or "v" in body:
        try:
            from l2.protocol.host import get_protocol_host

            return {"success": True, "envelopes": get_protocol_host().handle_message(body)}
        except Exception as e:
            return {"success": False, "error": f"shell protocol dispatch failed: {e}"}
    text = str(body.get("text", ""))
    if not text:
        return {"success": False, "error": "missing 'text' field"}
    try:
        from l2.l2_shell import dispatch

        session = None
        session_cfg = body.get("session")
        if isinstance(session_cfg, dict) and session_cfg:
            from l2.shells.session import ShellSession

            session = ShellSession(
                shell=str(session_cfg.get("shell", "")),
                session_id=str(session_cfg.get("session_id", "")),
            )
        return dispatch(text, session)
    except Exception as e:
        return {"success": False, "error": f"shell dispatch failed: {e}"}


def _shell_autocomplete(body: dict | None = None) -> dict:
    """Return auto-completion suggestions for a partial shell input line.

    Request: ``{"text": "...", "session": {...}}`` — ``text`` is the
    partial line to complete (commands, agents, roles).
    """
    body = body or {}
    line = str(body.get("text", ""))
    try:
        from l2.l2_shell.completer import autocomplete

        return {"success": True, "suggestions": autocomplete(line)}
    except Exception as e:
        return {"success": False, "error": f"shell autocomplete failed: {e}"}


def _shell_commands(body: dict | None = None) -> dict:
    """Return the available shell commands from the L2 command registry.

    Request: ``{"category": ""}`` — optional category filter (empty = all).
    """
    body = body or {}
    category = str(body.get("category", ""))
    try:
        from l1.kernel.commands import get_registry

        return {"success": True, "commands": get_registry().list(category)}
    except Exception as e:
        return {"success": False, "error": f"shell commands failed: {e}"}


def handle_agent_config_get(body: dict | None = None) -> dict:
    """GET /api/v1/agents/config — return current agent config."""
    from l1.kernel.params.agent import (
        AGENT_CLEARANCE,
        AGENT_PRIORITY,
        AGENT_ROLE_MAP,
        CENTRAL_DEFAULT_ROLES,
        CENTRAL_ROLES,
        DEFAULT_AGENT_CONFIGS,
    )

    return {
        "success": True,
        "central_roles": list(CENTRAL_ROLES),
        "default_roles": list(CENTRAL_DEFAULT_ROLES),
        "agent_role_map": {str(k): v for k, v in AGENT_ROLE_MAP.items()},
        "agent_priority": dict(AGENT_PRIORITY),
        "clearance": dict(AGENT_CLEARANCE),
        "agent_defaults": {
            role: {
                "ring": cfg.ring,
                "max_scouts": cfg.max_scouts,
                "max_tokens": cfg.max_tokens,
                "priority": cfg.priority,
            }
            for role, cfg in DEFAULT_AGENT_CONFIGS.items()
        },
    }


def handle_agent_config_set(body: dict | None = None) -> dict:
    """PUT /api/v1/agents/config — update agent config at runtime.

    Accepts any of:
      {"agent_role_map": {"1": "reader", "2": "writer", "3": "reviewer"}}
      {"agent_priority": {"reader": 5, "writer": 5, "reviewer": 5}}
      {"clearance": {"reader": 3, "writer": 3, "reviewer": 3}}
      {"default_roles": ["reader", "writer", "reviewer"]}
    """
    b = body or {}
    results = {}

    if "agent_role_map" in b:
        from l1.kernel.params.agent import AGENT_ROLE_MAP

        AGENT_ROLE_MAP.clear()
        for k, v in b["agent_role_map"].items():
            AGENT_ROLE_MAP[int(k)] = str(v)
        results["agent_role_map"] = len(AGENT_ROLE_MAP)

    if "agent_priority" in b:
        from l1.kernel.params.agent import AGENT_PRIORITY

        AGENT_PRIORITY.clear()
        AGENT_PRIORITY.update(b["agent_priority"])
        results["agent_priority"] = len(AGENT_PRIORITY)

    if "clearance" in b:
        from l1.kernel.params.agent import AGENT_CLEARANCE

        AGENT_CLEARANCE.clear()
        AGENT_CLEARANCE.update(b["clearance"])
        results["clearance"] = len(AGENT_CLEARANCE)

    if "default_roles" in b:
        from l1.kernel.params.agent import CENTRAL_DEFAULT_ROLES

        CENTRAL_DEFAULT_ROLES.clear()
        CENTRAL_DEFAULT_ROLES.extend(str(r) for r in b["default_roles"])
        results["default_roles"] = len(CENTRAL_DEFAULT_ROLES)

    if not results:
        return {
            "success": False,
            "error": "no supported fields in body; try agent_role_map, agent_priority, clearance, or default_roles",
        }

    return {"success": True, "updated": results}


def session_monitor_get(body: dict | None = None) -> dict:
    """Real-time session monitor: running status / resource / progress.

    Args:
        body: optional dict (unused — monitor is global).

    Returns:
        dict with per-session states (dual identity + status + counters).
    """
    from l3.agent_terminal import session_monitor, session_monitor_status

    return {"status": session_monitor_status(), **session_monitor()}


def session_monitor_set(body: dict) -> dict:
    """Enable/disable the session monitor (3.3, default ON)."""
    from l3.agent_terminal import set_session_monitor

    enabled = body.get("enabled")
    return set_session_monitor(enabled=None if enabled is None else bool(enabled))


def session_reload_post(body: dict) -> dict:
    """Auto-reload a session entity on anomaly / trigger reload (3.3).

    Args:
        body: dict with ``agent_id`` (required) and optional ``reason``
            (anomaly reason, e.g. a stagnation pattern).

    Returns:
        dict with the reload outcome (or a no-op note).
    """
    from l3.agent_terminal import auto_reload_session

    agent_id = str(body.get("agent_id", "") or "")
    if not agent_id:
        return {"success": False, "error": "agent_id required"}
    return auto_reload_session(agent_id, reason=str(body.get("reason", "") or ""))


def session_history_get(body: dict | None = None) -> dict:
    """Session history records (start/end/duration, query, 3.3)."""
    from l3.cell.peers.l3a.session_json import history_status, query_session_history

    b = body or {}
    limit = int(b.get("limit", 20) or 20)
    session_id = str(b.get("session_id", "") or "")
    return {"status": history_status(), **query_session_history(limit=limit, session_id=session_id)}


def session_history_set(body: dict) -> dict:
    """Enable/disable the session history module (3.3, default ON)."""
    from l3.cell.peers.l3a.session_json import set_history

    enabled = body.get("enabled")
    return set_history(enabled=None if enabled is None else bool(enabled))
