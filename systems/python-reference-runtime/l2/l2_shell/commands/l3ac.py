"""L2 shell command — L3A-C secretary management.

Subcommands: status | contribute <kind> <true|false> [--card id] | reset.
The secretary records contributions and upgrades assist → peer at the
capability threshold (L3AC_CAPABILITY_THRESHOLD).
"""

from __future__ import annotations

from l2.i18n import t as _t


def _cmd_l3ac(args: list[str]) -> dict:
    """Manage the L3A-C secretary: status | contribute | reset."""
    sub = args[0] if args else "status"
    if sub == "reset":
        from l3.cell.peers.l3a.secretary import reset_secretary

        reset_secretary()
        return {"success": True, "note": "secretary reset"}
    from l3.cell.peers.l3a.secretary import get_secretary

    sec = get_secretary()
    if sub == "status":
        return {"success": True, "secretary": sec.status()}
    if sub == "contribute":
        if len(args) < 3:
            return {"success": False, "error": _t("shell.app_error.usage_l3ac_contribute")}
        kind = args[1]
        raw = args[2].lower()
        if raw not in ("true", "yes", "1", "false", "no", "0"):
            return {"success": False, "error": f"invalid boolean: {args[2]} (true|false)"}
        ok = raw in ("true", "yes", "1")
        card_id = args[4] if len(args) > 4 and args[3] == "--card" else ""
        return sec.contribute(kind, success=ok, card_id=card_id)
    return {"success": False, "error": f"unknown subcommand: {sub} (status|contribute|reset)"}
