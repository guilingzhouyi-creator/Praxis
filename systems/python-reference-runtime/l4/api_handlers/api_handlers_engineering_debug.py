"""Engineering debug mode and developer prompt-management API handlers."""

from __future__ import annotations


def engineering_debug_get(body: dict | None = None) -> dict:
    """Return marker, mode, logging, prompt-monitor and input status."""
    from l3.tool_system.engineering_debug import engineering_debug_status

    return engineering_debug_status()


def engineering_debug_set(body: dict) -> dict:
    """Set the requested engineering debug mode with a developer gate."""
    b = body or {}
    mode = str(b.get("mode", "") or "").strip().lower()
    if not mode:
        return {"success": False, "error": "mode is required (auto|on|off)"}
    from l3.tool_system.engineering_debug import get_engineering_debug

    return get_engineering_debug().set_mode(
        mode,
        actor_id=str(b.get("_user_id", b.get("agent_id", "")) or ""),
        role=str(b.get("writer_role", b.get("role", "")) or ""),
        ring=b.get("ring", 0),
        source="api",
    )


def engineering_debug_prompt_get(body: dict | None = None) -> dict:
    """List prompt layers and version metadata for engineering inspection."""
    from l3.tool_system.engineering_debug import get_engineering_debug

    return get_engineering_debug().prompt_status()


def engineering_debug_prompt_set(body: dict) -> dict:
    """Set one runtime prompt overlay after developer authorization."""
    b = body or {}
    if "key" not in b or "text" not in b:
        return {"success": False, "error": "key and text are required"}
    from l3.tool_system.engineering_debug import get_engineering_debug

    return get_engineering_debug().set_prompt_override(
        str(b.get("key", "")),
        str(b.get("text", "")),
        actor_id=str(b.get("_user_id", b.get("agent_id", "")) or ""),
        role=str(b.get("writer_role", b.get("role", "")) or ""),
        ring=b.get("ring", 0),
        source="api",
    )


def engineering_debug_prompt_rollback(body: dict) -> dict:
    """Roll one prompt overlay back to a recorded version."""
    b = body or {}
    try:
        version = int(b.get("version", 0))
    except (TypeError, ValueError):
        return {"success": False, "error": "version must be an integer"}
    from l3.tool_system.engineering_debug import get_engineering_debug

    return get_engineering_debug().rollback_prompt(
        str(b.get("key", "")),
        version,
        actor_id=str(b.get("_user_id", b.get("agent_id", "")) or ""),
        role=str(b.get("writer_role", b.get("role", "")) or ""),
        ring=b.get("ring", 0),
        source="api",
    )


def engineering_debug_input_get(body: dict | None = None) -> dict:
    """Return privacy-preserving input activity status."""
    from l3.tool_system.input_activity import get_input_activity

    return get_input_activity().status()


def engineering_debug_input_set(body: dict) -> dict:
    """Enable or disable aggregate input activity observation."""
    b = body or {}
    if "enabled" not in b:
        return {"success": False, "error": "enabled is required"}
    enabled = b["enabled"]
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in ("true", "1", "on")
    from l3.tool_system.input_activity import get_input_activity

    return get_input_activity().set_enabled(
        bool(enabled),
        actor_id=str(b.get("_user_id", b.get("agent_id", "")) or ""),
        role=str(b.get("writer_role", b.get("role", "")) or ""),
        ring=b.get("ring", 0),
        source="api",
    )
