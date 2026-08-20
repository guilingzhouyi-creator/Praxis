"""L2 Shell: marker-gated engineering debug controls."""

from __future__ import annotations

from l2.i18n import t as _t


def _parse_operator_flags(args: list[str]) -> tuple[str, str, int]:
    """Extract the explicit developer identity flags from an L2 command."""
    role = ""
    actor_id = ""
    ring = 0
    index = 0
    while index < len(args):
        value = args[index]
        if value == "--role" and index + 1 < len(args):
            role = args[index + 1]
            index += 2
            continue
        if value.startswith("--role="):
            role = value.split("=", 1)[1]
        elif value == "--agent" and index + 1 < len(args):
            actor_id = args[index + 1]
            index += 2
            continue
        elif value.startswith("--agent="):
            actor_id = value.split("=", 1)[1]
        elif value == "--ring" and index + 1 < len(args):
            try:
                ring = int(args[index + 1])
            except (TypeError, ValueError):
                ring = 0
            index += 2
            continue
        elif value.startswith("--ring="):
            try:
                ring = int(value.split("=", 1)[1])
            except (TypeError, ValueError):
                ring = 0
        index += 1
    return actor_id, role, ring


def _cmd_debug_mode(args: list[str], session=None) -> dict:
    """Show or switch engineering debug mode (auto|on|off|reset)."""
    from l3.tool_system.engineering_debug import get_engineering_debug

    if not args or args[0].lower() in ("status", "show"):
        return get_engineering_debug().status()
    sub = args[0].lower()
    actor_id, role, ring = _parse_operator_flags(args[1:])
    manager = get_engineering_debug()
    if sub == "reset":
        return manager.reset_mode(actor_id=actor_id, role=role, ring=ring, source="shell")
    if sub not in ("auto", "on", "off"):
        return {"success": False, "error": _t("shell.app_error.usage_debug_mode")}
    return manager.set_mode(sub, actor_id=actor_id, role=role, ring=ring, source="shell")
