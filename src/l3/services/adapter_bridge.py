"""Adapter bridge — thin L3 wrappers for L4 services.

Eliminates L2→L4 direct imports by providing L3 service wrappers
that L2 shell commands call instead of importing L4 directly.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_llm_engine():
    """Get the LLM engine instance (wraps l4.llm.llm.get_engine)."""
    from l4.llm.llm import get_engine

    return get_engine()


def get_mcp_bridge():
    """Get the MCP bridge and client (wraps l4.mcp_bridge)."""
    from l4.mcp_bridge import McpClient, get_bridge  # noqa: F401

    return get_bridge(), McpClient


def get_cron_scheduler():
    """Get the cron scheduler (wraps l4.cron_scheduler)."""
    from l4.cron_scheduler import get_scheduler

    return get_scheduler()


def export_vault_status() -> dict:
    """Export vault credential status (wraps l4.vault.credential_vault)."""
    from l4.vault.credential_vault import export_vault_status

    return export_vault_status()


def get_mcp_status() -> dict:
    """Get MCP server status and tool export counts."""
    from l4.mcp_bridge import get_bridge

    bridge = get_bridge()
    data = {"servers": bridge.get_status()}
    try:
        from l4.api_handlers.api_handlers_mcp import get_export_mode, handle_mcp_tools_list

        data["server_mode"] = get_export_mode()
        data["exported_tools"] = handle_mcp_tools_list().get("count", 0)
    except Exception:
        logger.debug("adapter_bridge: mcp status enrichment failed", exc_info=True)
    return data


def set_mcp_export_mode(mode: str) -> dict:
    """Set MCP tool export mode (wraps l4.api_handlers.api_handlers_mcp)."""
    from l4.api_handlers.api_handlers_mcp import set_export_mode

    set_export_mode(mode)
    return {"server_mode": mode}


def get_ci_review_service():
    """Get the CiReviewService instance (wraps l4.ci_review.get_service)."""
    from l4.ci_review import get_service

    return get_service()


def normalize_ci_key(key: str) -> str:
    """Normalize a CI setting key (wraps l4.ci_review._normalize_key)."""
    from l4.ci_review import _normalize_key

    return _normalize_key(key)


def get_ci_setting_suffixes() -> frozenset[str]:
    """Get allowed CI setting suffixes (wraps l4.ci_review.CI_SETTING_SUFFIXES)."""
    from l4.ci_review import CI_SETTING_SUFFIXES

    return CI_SETTING_SUFFIXES


def is_ci_allowed_key(key: str) -> bool:
    """Check if a CI key is allowed (wraps l4.ci_review._is_allowed_key)."""
    from l4.ci_review import _is_allowed_key

    return _is_allowed_key(key)


def is_ci_control_key(key: str) -> bool:
    """Check if a CI key is a control key (wraps l4.ci_review._is_control_key)."""
    from l4.ci_review import _is_control_key

    return _is_control_key(key)
