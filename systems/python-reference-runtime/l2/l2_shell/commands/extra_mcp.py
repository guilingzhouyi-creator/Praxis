"""L2 Shell: MCP bridge commands.

Extracted from ``extra.py`` (per-domain split).  Owns the MCP server
status / mode / enable / disable inspection commands.
"""

from __future__ import annotations

import logging

from l2.i18n import t as _t
from l3.error_bus import capture

logger = logging.getLogger(__name__)


def _cmd_mcp(args: list[str]) -> dict:
    try:
        from l3.services.adapter_bridge import get_mcp_bridge, get_mcp_status, set_mcp_export_mode

        bridge, _ = get_mcp_bridge()
        sub = args[0].lower() if args else "status"
        if sub in ("status", "list"):
            return {"success": True, "data": get_mcp_status()}
        if sub == "mode" and len(args) >= 2:
            return {"success": True, "data": set_mcp_export_mode(args[1])}
        if sub == "enable" and len(args) >= 2:
            return bridge.set_enabled(args[1])
        if sub == "disable" and len(args) >= 2:
            return bridge.set_disabled(args[1])
        return {"success": False, "error": _t("shell.app_error.usage_mcp")}
    except Exception as e:
        capture("extra: cmd failed", error_code="E_CMD", component="l2", context={"error": str(e)})
        return {"success": False, "error": str(e)}
