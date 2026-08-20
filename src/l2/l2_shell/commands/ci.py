"""L2 Shell: card-triggered CI review command (ci)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from l2.i18n import t as _t

logger = logging.getLogger(__name__)


def _parse_value(raw: str):
    """Parse a CLI value into bool / int / list / str."""
    v = raw.strip()
    low = v.lower()
    if low in ("true", "on", "yes", "1"):
        return True
    if low in ("false", "off", "no", "0"):
        return False
    if v.startswith("[") and v.endswith("]"):
        return [i.strip().strip("'\"") for i in v[1:-1].split(",") if i.strip()]
    try:
        return int(v)
    except ValueError:
        return v


def _parse_flags(args: list[str]) -> tuple[list[str], str, str, bool]:
    """Split trailing flags from positional args.

    Returns (positional, cell_id, agent_id, admin).  Recognised flags:
    ``--cell <id>``, ``--agent <id>``, ``--admin``.
    """
    cell_id = ""
    agent_id = ""
    admin = False
    rest: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--cell" and i + 1 < len(args):
            cell_id = args[i + 1]
            i += 2
        elif a == "--agent" and i + 1 < len(args):
            agent_id = args[i + 1]
            i += 2
        elif a == "--admin":
            admin = True
            i += 1
        else:
            rest.append(a)
            i += 1
    return rest, cell_id, agent_id, admin


def _resolve_scope_key(key: str, cell_id: str, agent_id: str) -> str:
    """Resolve a key (with optional scope) into the concrete settings key."""
    from l4.ci_review import _normalize_key

    full = _normalize_key(key)
    if full.startswith(("ci.review.cell.", "ci.review.agent.", "ci.control.")):
        return full
    suffix = full[len("ci.review.") :] if full.startswith("ci.review.") else full
    if cell_id:
        return f"ci.review.cell.{cell_id}.{suffix}"
    if agent_id:
        return f"ci.review.agent.{agent_id}.{suffix}"
    return f"ci.review.{suffix}"


def _ci_list(svc, rest: list[str], *_context: object) -> dict:
    """`ci list [status]` — query review records by status."""
    status = rest[1] if len(rest) > 1 else ""
    return svc.query(status=status)


def _ci_show(svc, rest: list[str], *_context: object) -> dict:
    """`ci show <card_id>` — show a single review record."""
    if len(rest) < 2:
        return {"success": False, "error": _t("shell.app_error.usage_ci_show")}
    return svc.query(card_id=rest[1], limit=1)


def _ci_rerun(svc, rest: list[str], *_context: object) -> dict:
    """`ci rerun <card_id>` — rerun a review (write surface required)."""
    if len(rest) < 2:
        return {"success": False, "error": _t("shell.app_error.usage_ci_rerun")}
    if not svc._surface_writable("shell"):
        return {"success": False, "error": _t("shell.app_error.ci_writes_disabled")}
    return svc.rerun(rest[1])


def _ci_config(svc, center, rest: list[str], cell_id: str, agent_id: str, _admin: bool = False) -> dict:
    """`ci config [--cell X] [--agent Y]` — show global/effective settings."""
    from l4.ci_review import CI_SETTING_SUFFIXES

    settings: dict = {}
    effective: dict = {}
    for suffix in sorted(CI_SETTING_SUFFIXES):
        global_key = f"ci.review.{suffix}"
        settings[global_key] = center.get(global_key)
        effective[suffix] = svc._effective(suffix, agent_id, cell_id, center.get(global_key))
    return {
        "success": True,
        "settings": settings,
        "effective": effective,
        "scope": {"cell": cell_id, "agent": agent_id},
        "control": {
            "api": {"writable": svc._surface_writable("api")},
            "shell": {"writable": svc._surface_writable("shell")},
        },
    }


def _ci_set(svc, center, rest: list[str], cell_id: str, agent_id: str, admin: bool) -> dict:
    """`ci set <key> <value> [--cell X] [--agent Y] [--admin]` — set a review setting."""
    from l4.ci_review import CI_SETTING_SUFFIXES, _is_allowed_key, _is_control_key

    if len(rest) < 3:
        return {"success": False, "error": _t("shell.app_error.usage_ci_set")}
    full_key = _resolve_scope_key(rest[1], cell_id, agent_id)
    if not _is_allowed_key(full_key):
        return {
            "success": False,
            "error": _t("shell.app_error.key_not_writable", full_key=full_key),
            "allowed": sorted(CI_SETTING_SUFFIXES),
        }
    if _is_control_key(full_key):
        if not admin:
            return {"success": False, "error": _t("shell.app_error.admin_confirmation_required", full_key=full_key)}
    elif not svc._surface_writable("shell"):
        return {"success": False, "error": _t("shell.app_error.ci_writes_disabled")}
    value = _parse_value(" ".join(rest[2:]))
    center.set(full_key, value)
    return {"success": True, "key": full_key, "value": value}


def _ci_toggle(svc, center, rest: list[str], cell_id: str, agent_id: str, admin: bool) -> dict:
    """`ci toggle [--cell X] [--agent Y] [--admin]` — flip the enabled switch."""
    from l4.ci_review import _is_control_key

    full_key = _resolve_scope_key("enabled", cell_id, agent_id)
    if _is_control_key(full_key) and not admin:
        return {"success": False, "error": _t("shell.app_error.ci_admin_required")}
    if not svc._surface_writable("shell"):
        return {"success": False, "error": _t("shell.app_error.ci_writes_disabled")}
    enabled = not bool(center.get(full_key, True))
    center.set(full_key, enabled)
    return {"success": True, "key": full_key, "enabled": enabled}


_CI_HANDLERS: dict[str, Callable] = {
    "list": _ci_list,
    "show": _ci_show,
    "rerun": _ci_rerun,
    "config": _ci_config,
    "set": _ci_set,
    "toggle": _ci_toggle,
}


def _cmd_ci(args: list[str], session=None) -> dict:
    """Show CI review stats/reports, inspect or set review switches.

    Sub-commands: ``config [--cell X] [--agent Y]``, ``set <key> <value>
    [--cell X] [--agent Y] [--admin]``, ``toggle [--cell X] [--agent Y]
    [--admin]``, ``list [status]``, ``show <card_id>``.
    """
    try:
        from l3.config.settings_center import get_center
        from l4.ci_review import get_service

        rest, cell_id, agent_id, admin = _parse_flags(args)
        svc = get_service()
        center = get_center()
        if not rest:
            return {"success": True, **svc.stats()}
        handler = _CI_HANDLERS.get(rest[0].lower())
        if not handler:
            return {
                "success": False,
                "error": _t("shell.app_error.unknown_ci_subcommand", sub=rest[0].lower()),
            }
        return handler(svc, center, rest, cell_id, agent_id, admin)
    except Exception as e:
        return {"success": False, "error": _t("shell.app_error.ci_review_error", error=e)}
