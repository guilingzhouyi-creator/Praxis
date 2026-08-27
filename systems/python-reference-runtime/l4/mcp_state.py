"""MCP state — persisted connection state (5-state machine per server).

Extracted from ``mcp_bridge.py``: the status vocabulary and the
``mcp_state.json`` read/write helpers used by the bridge for recovery
across restarts.
"""

from __future__ import annotations

import json
import logging
import os
import time

from l1.kernel.params.system import MCP_STATE_FILENAME
from l1.kernel.platform import ensure_dir

logger = logging.getLogger(__name__)

MCP_STATUS_CONNECTED = "connected"
MCP_STATUS_DISABLED = "disabled"
MCP_STATUS_FAILED = "failed"
MCP_STATUS_NEEDS_AUTH = "needs_auth"
MCP_STATUS_NEEDS_REGISTRATION = "needs_client_registration"

MCP_STATE_PATH: str = ""


def _mcp_state_path() -> str:
    global MCP_STATE_PATH
    if not MCP_STATE_PATH:
        try:
            from l1.kernel.paths import get_paths as _gp

            MCP_STATE_PATH = _gp().mcp_state
        except Exception:
            MCP_STATE_PATH = os.environ.get("PRAXIS_MCP_STATE", MCP_STATE_FILENAME)
    return MCP_STATE_PATH


def _save_mcp_state(servers: dict[str, dict]) -> None:
    """Persist MCP server state to disk."""
    try:
        path = _mcp_state_path()
        ensure_dir(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"servers": servers, "updated_at": time.time()}, f, indent=2)
    except Exception as e:
        logger.warning("mcp: save state failed: %s", e)


def _load_mcp_state() -> dict[str, dict]:
    """Load persisted MCP server state."""
    try:
        path = _mcp_state_path()
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("servers", {})
    except Exception as e:
        logger.warning("mcp: load state failed: %s", e)
    return {}
