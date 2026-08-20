"""L2 Shell: MCP bridge commands.

Extracted from ``extra.py`` (per-domain split).  Owns the MCP server
status / mode / enable / disable inspection commands.
"""

from __future__ import annotations

import logging

from l2.i18n import t as _t
from l3.error_bus import capture

logger = logging.getLogger(__name__)


def _cmd_mcp(args: list[str], session=None) -> dict:
    try:
        from l4.mcp_bridge import get_bridge

        bridge = get_bridge()
        sub = args[0].lower() if args else "status"
        if sub in ("status", "list"):
            data = {"servers": bridge.get_status()}
            try:
                from l4.api_handlers.api_handlers_mcp import get_export_mode, handle_mcp_tools_list

                data["server_mode"] = get_export_mode()
                data["exported_tools"] = handle_mcp_tools_list().get("count", 0)
            except Exception:
                logger.debug("extra: mcp status enrichment failed", exc_info=True)
            return {"success": True, "data": data}
        if sub == "mode" and len(args) >= 2:
            from l4.api_handlers.api_handlers_mcp import set_export_mode

            set_export_mode(args[1])
            return {"success": True, "data": {"server_mode": args[1]}}
        if sub == "enable" and len(args) >= 2:
            return bridge.set_enabled(args[1])
        if sub == "disable" and len(args) >= 2:
            return bridge.set_disabled(args[1])
        return {"success": False, "error": _t("shell.app_error.usage_mcp")}
    except Exception as e:
        capture("extra: cmd failed", error_code="E_CMD", component="l2", context={"error": str(e)})
        return {"success": False, "error": str(e)}
