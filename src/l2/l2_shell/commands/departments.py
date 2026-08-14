"""L2 shell command — department division management.

Subcommands: status | route <content-type> [--cells N] | enable | disable.
The enable switch is a settings flat key (departments.enabled), controllable
at runtime via the same surface the /api/v2/settings endpoint writes to.
"""

from __future__ import annotations

from l2.i18n import t as _t


def _cmd_departments(args: list[str]) -> dict:
    """Manage department division: status | route | enable | disable."""
    sub = args[0] if args else "status"
    if sub in ("enable", "disable"):
        from l1.kernel.settings import get_settings

        get_settings().set("departments.enabled", sub == "enable")
        return {"success": True, "note": f"departments {'enabled' if sub == 'enable' else 'disabled'}"}
    from l3.cell.department import get_department_manager

    mgr = get_department_manager()
    if sub == "status":
        return {"success": True, "departments": mgr.status()}
    if sub == "route":
        content_type = args[1] if len(args) > 1 else "test"
        cell_count = None
        rest = args[2:]
        if "--cells" in rest:
            idx = rest.index("--cells")
            if idx + 1 >= len(rest):
                return {"success": False, "error": _t("shell.app_error.departments_cells_int_required")}
            try:
                cell_count = int(rest[idx + 1])
            except ValueError:
                return {"success": False, "error": _t("shell.app_error.departments_cells_int_invalid")}
        return {"success": True, "route": mgr.route_content(content_type, cell_count=cell_count)}
    return {"success": False, "error": f"unknown subcommand: {sub} (status|route|enable|disable)"}
