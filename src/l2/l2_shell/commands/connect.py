"""L2 Shell: connection and mode commands (agents, connect, mode, help).

TS rewrite reference: connection/mode commands forward through the bridge
(selector/memory domains) — the TS side maps them to dispatcher entries
whose fallback routes to the bridge marker; no local authority.
"""

from __future__ import annotations

import logging

from l2.i18n import t as _t
from l2.selector import preselect

logger = logging.getLogger(__name__)


def _cmd_help(args: list[str], session=None) -> dict:
    from l1.kernel.commands import get_command

    from .common import list_commands

    try:
        if args:
            cmd_name = args[0].lower().lstrip("/")
            cmd = get_command(cmd_name)
            if not cmd:
                return {"success": False, "error": _t("shell.app_error.unknown_command", cmd_name=cmd_name)}
            lines = [f"/{cmd_name}  — {cmd.get('help', '')}"]
            if cmd.get("aliases"):
                lines.append(f"  aliases: {', '.join('/' + a for a in cmd['aliases'])}")
            if cmd.get("args"):
                lines.append("  args:")
                for a in cmd["args"]:
                    opt = " (optional)" if a.get("optional") else ""
                    lines.append(f"    {a['name']}{opt} — {a.get('description', '')}")
            if cmd.get("examples"):
                lines.append("  examples:")
                for e in cmd["examples"]:
                    lines.append(f"    {e}")
            lines.append(f"  category: {cmd.get('category', 'other')}")
            return {"success": True, "output": "\n".join(lines), "format": "table"}
        cmds = list_commands()
        groups: dict[str, list] = {}
        for c in cmds:
            groups.setdefault(c.get("category", "other"), []).append(c)
        cat_labels = {
            "session": _t("shell.render.cat_session"),
            "control": _t("shell.render.cat_control"),
            "memory": _t("shell.render.cat_memory"),
            "system": _t("shell.render.cat_system"),
            "agent": _t("shell.render.cat_agent"),
            "audit": _t("shell.render.cat_audit"),
            "ext": _t("shell.render.cat_ext"),
        }
        lines = [_t("shell.render.available"), ""]
        for cat in ["session", "control", "memory", "system", "agent", "audit", "ext"]:
            items = groups.get(cat, [])
            if not items:
                continue
            lines.append(f"  ── {cat_labels.get(cat, cat)} ──")
            for c in items:
                alias_str = f" ({', '.join('/' + a for a in c['aliases'])})" if c.get("aliases") else ""
                lines.append(f"    {c['command']:25s} {c.get('help', '')}{alias_str}")
            lines.append("")
        lines.append("  Tip: /help <command> for details & examples")
        lines.append("  Tip: cmd1 | cmd2 pipes the previous output as the next command's first argument")
        lines.append("  Tip: --cell or --agent for scoped operations")
        return {"success": True, "output": "\n".join(lines), "format": "table"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_agents(args: list[str], session=None) -> dict:
    try:
        return {"success": True, "data": preselect()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_connect(args: list[str], session=None) -> dict:
    from l2.bridge import terminals

    if not args:
        return {"success": False, "error": _t("shell.app_error.usage_connect")}
    from l1.kernel.params.agent import DEFAULT_CELL_ID
    from l2.bridge import cell as _get_cell
    from l2.selector import select as _select

    from ..state import get_state

    agent_id = args[0]
    terms = terminals()
    if agent_id not in terms:
        return {"success": False, "error": _t("shell.app_error.unknown_agent", agent_id=agent_id)}
    state = session if session is not None else get_state()
    # Route through the selector so bare agent ids resolve across cells
    # instead of pinning to the default cell.
    resolved = _select(agent_id=agent_id)
    cell_id = resolved["cell_id"] if resolved.get("success") else DEFAULT_CELL_ID
    try:
        cell = _get_cell(cell_id)
        r = cell.send_direct_message(agent_id, "")
        if not r.get("success"):
            return {"success": False, "error": r.get("error", "connect failed")}
    except Exception as e:
        logger.warning("connect: send_direct_message failed: %s", e)
    state.switch_to_direct(cell_id, agent_id)
    return {"success": True, "agent": agent_id, "cell_id": cell_id}


def _cmd_disconnect(args: list[str], session=None) -> dict:
    from ..state import get_state

    state = session if session is not None else get_state()
    if not state.is_direct():
        return {"success": False, "error": _t("shell.app_error.no_active_session")}
    try:
        from l2.bridge import cell as _get_cell

        cell = _get_cell(state.cell_id)
        cell.close_direct_session(state.agent_id)
    except Exception as e:
        logger.warning("connect: close_direct_session failed: %s", e)
    state.switch_to_l3a()
    return {"success": True}


def _cmd_mode(args: list[str], session=None) -> dict:
    from ..state import get_state

    state = session if session is not None else get_state()
    if args:
        sub = args[0].lower()
        if sub == "direct":
            if not state.agent_id:
                return {"success": False, "error": _t("shell.app_error.no_agent_connected")}
            state.switch_to_direct(state.cell_id, state.agent_id)
            return {
                "success": True,
                "mode": "DIRECT",
                "cell_id": state.cell_id,
                "current_tool_mode": getattr(state, "tool_mode", "read"),
            }
        if sub == "tool":
            requested = args[1].lower() if len(args) > 1 else "toggle"
            current = getattr(state, "tool_mode", "read")
            if requested == "toggle":
                new_mode = "write" if current == "read" else "read"
            elif requested in ("read", "write"):
                new_mode = requested
            else:
                return {"success": False, "error": _t("shell.render.unknown_error")}
            persisted = state.set_tool_mode(new_mode)
            return {"success": True, "mode": state.mode, "cell_id": state.cell_id, "current_tool_mode": persisted}
        return {"success": False, "error": _t("shell.app_error.unknown_mode_subcommand", sub=sub)}
    return {
        "success": True,
        "mode": state.mode,
        "cell_id": state.cell_id,
        "current_tool_mode": getattr(state, "tool_mode", "read"),
    }
