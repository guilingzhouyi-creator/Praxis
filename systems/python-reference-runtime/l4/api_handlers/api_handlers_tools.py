"""API handler mixin — tool stats / policy and cache handlers.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def tool_stats(body: dict | None = None) -> dict:
    """Tool usage summary from the central counter."""
    try:
        from l3.services.counter import get_counter

        return get_counter().tool_summary()
    except Exception as e:
        return {"error": str(e)}


def tool_policy_set(body: dict) -> dict:
    """Add a tool policy rule."""
    try:
        from l3.tool_system.tool_policy import PolicyAction, PolicyRule, PolicyScope, ToolPolicy

        scope_str = body.get("scope", "global")
        scope_parts = scope_str.split(":", 1)
        scope = PolicyScope(scope_parts[0])
        scope_id = scope_parts[1] if len(scope_parts) > 1 else ""
        rule = PolicyRule(
            scope=scope,
            scope_id=scope_id,
            tool=body.get("tool", "*"),
            action=PolicyAction(body.get("action", "disable")),
            reason=body.get("reason", ""),
        )
        ToolPolicy.add(rule)
        return {"success": True, "rule": rule.key()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_policy_list(body: dict | None = None) -> dict:
    """List tool policy rules."""
    try:
        from l3.tool_system.tool_policy import ToolPolicy

        return {"success": True, "policies": ToolPolicy.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_policy_remove(body: dict) -> dict:
    """Remove a tool policy rule."""
    try:
        from l3.tool_system.tool_policy import PolicyScope, ToolPolicy

        scope_str = body.get("scope", "global")
        scope_parts = scope_str.split(":", 1)
        scope = PolicyScope(scope_parts[0])
        scope_id = scope_parts[1] if len(scope_parts) > 1 else ""
        ok = ToolPolicy.remove(tool=body.get("tool", "*"), scope=scope, scope_id=scope_id)
        return {"success": ok}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cache_stats(body: dict | None = None) -> dict:
    """Per-agent terminal file-cache statistics."""
    try:
        from l3.agent_terminal import get_terminals

        seen = {}
        for aid, term in get_terminals().items():
            try:
                seen[aid] = term.file_cache.stats()
            except Exception as e:
                logger.warning("cache_stats: %s", e)
        return {"caches": seen, "count": len(seen)}
    except Exception as e:
        return {"error": str(e)}


def tool_register(body: dict) -> dict:
    """POST /api/v2/tools/register — dynamically register a tool from a dict spec.

    Body: ``{"name": ..., "spec": {description/handler/params/danger/...}, "ring": "ring_1"}``.
    The spec goes through ToolConfig.register_from_dict — ring whitelist and
    the dynamic cap are enforced; handler resolution is validated eagerly.
    """
    try:
        from l3.tool_system.tool_config import ToolConfig

        name = body.get("name", "")
        spec = body.get("spec") or {}
        ring = body.get("ring", "ring_1")
        if not name or not isinstance(spec, dict) or not spec:
            return {"success": False, "error": "name and spec (dict) required"}
        return ToolConfig.register_from_dict(name, spec, ring=ring)
    except Exception as e:
        logger.warning("tool_register: %s", e)
        return {"success": False, "error": str(e)}


def tool_unregister(body: dict) -> dict:
    """POST /api/v2/tools/unregister — remove a dynamically registered tool."""
    try:
        from l3.tool_system.tool_registry import get_registry

        name = body.get("name", "")
        if not name:
            return {"success": False, "error": "name required"}
        ok = get_registry().unregister(name)
        return {"success": ok, "name": name}
    except Exception as e:
        logger.warning("tool_unregister: %s", e)
        return {"success": False, "error": str(e)}
