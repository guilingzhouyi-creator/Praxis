"""L2 Shell: privacy-preserving aggregate input activity controls."""

from __future__ import annotations

from l2.i18n import t as _t

from .engineering_debug import _parse_operator_flags


def _cmd_debug_input(args: list[str]) -> dict:
    """Show or switch input activity monitoring (engineering mode only)."""
    from l3.tool_system.input_activity import get_input_activity

    if not args or args[0].lower() in ("status", "show"):
        return get_input_activity().status()
    sub = args[0].lower()
    if sub not in ("on", "off"):
        return {"success": False, "error": _t("shell.app_error.usage_debug_input")}
    actor_id, role, ring = _parse_operator_flags(args[1:])
    return get_input_activity().set_enabled(sub == "on", actor_id=actor_id, role=role, ring=ring, source="shell")
