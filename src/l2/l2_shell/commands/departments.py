"""L2 shell command — department division management.

Subcommands: status | route <content-type> [--cells N] | enable | disable |
define <dept-id> [--text "definition"] [--scope a,b] [--executor name].
The enable switch is a settings flat key (departments.enabled), controllable
at runtime via the same surface the /api/v2/settings endpoint writes to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from l2.i18n import t as _t

if TYPE_CHECKING:
    from l3.cell.department import DepartmentManager


def _set_switch(sub: str) -> dict:
    """Set the departments.enabled settings switch (enable/disable)."""
    from l1.kernel.settings import get_settings

    get_settings().set("departments.enabled", sub == "enable")
    return {"success": True, "note": f"departments {'enabled' if sub == 'enable' else 'disabled'}"}


def _dept_route(mgr: DepartmentManager, args: list[str]) -> dict:
    """Route a content type to its owning department (with optional --cells)."""
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


def _cmd_departments(args: list[str], session=None) -> dict:
    """Manage department division: status | route | enable | disable | define."""
    sub = args[0] if args else "status"
    if sub in ("enable", "disable"):
        return _set_switch(sub)
    from l3.cell.department import get_department_manager

    mgr = get_department_manager()
    if sub == "status":
        return {"success": True, "departments": mgr.status()}
    if sub == "route":
        return _dept_route(mgr, args)
    if sub == "define":
        return _dept_define(mgr, args)
    if sub == "monitor":
        return _dept_monitor(args)
    return {
        "success": False,
        "error": _t(
            "shell.app_error.unknown_subcommand_hint", sub=sub, hint="status|route|enable|disable|define|monitor"
        ),
    }


def _dept_monitor(args: list[str]) -> dict:
    """Manage the violation monitor: status | enable | disable.

    The monitor stays inert until department division is active (Cell count
    >= CELL_DEPARTMENT_MIN), even when enabled — see violation_monitor.
    """
    from l3.cell.violation_monitor import reset_violation_monitor, set_enabled, status

    sub = args[1] if len(args) > 1 else "status"
    if sub == "enable":
        return set_enabled(True)
    if sub == "disable":
        return set_enabled(False)
    if sub == "reset":
        reset_violation_monitor()
        return {"success": True, "monitor": status()}
    if sub == "status":
        return {"success": True, "monitor": status()}
    return {
        "success": False,
        "error": _t("shell.app_error.unknown_monitor_subcommand", sub=sub, hint="status|enable|disable|reset"),
    }


def _dept_define(mgr: DepartmentManager, args: list[str]) -> dict:
    """Update a registered department's definition / scope / executor (runtime).

    Usage: departments define <dept-id> [--text "definition"] [--scope a,b]
           [--executor name]. Reads current values when no option is given.
    """
    if len(args) < 2:
        return {"success": False, "error": _t("shell.app_error.usage_departments_define")}
    dept_id = args[1]
    dept = mgr._departments.get(dept_id)  # manager-internal view (read path)
    if dept is None:
        return {"success": False, "error": _t("shell.app_error.unknown_department", dept_id=dept_id)}
    rest = args[2:]
    text = ""
    if "--text" in rest:
        idx = rest.index("--text")
        if idx + 1 < len(rest):
            text = rest[idx + 1]
    scope = None
    if "--scope" in rest:
        idx = rest.index("--scope")
        if idx + 1 < len(rest):
            scope = [s.strip() for s in rest[idx + 1].split(",") if s.strip()]
    executor = None
    if "--executor" in rest:
        idx = rest.index("--executor")
        if idx + 1 < len(rest):
            executor = rest[idx + 1]
    if not text and scope is None and executor is None:
        return {
            "success": True,
            "department": dept_id,
            "definition": dept.definition,
            "permission_scope": list(dept.permission_scope),
            "executor": dept.executor,
        }
    if text:
        from l1.kernel.params.agent import DEPARTMENT_DEFINITION_MAX_CHARS

        dept.definition = text[:DEPARTMENT_DEFINITION_MAX_CHARS]
    if scope is not None:
        dept.permission_scope = scope
    if executor is not None:
        dept.executor = executor
    return {
        "success": True,
        "department": dept_id,
        "definition": dept.definition,
        "permission_scope": list(dept.permission_scope),
        "executor": dept.executor,
    }
