"""B4 linkage — card completion → tool usage statistics aggregation.

Registers a global card-completion listener that, when a card finishes,
summarizes the completing agent's tool usage (from CellCounter) and stores
the snapshot in the L1 registry section ``card_tool_stats``. Consumers
(status surfaces, L3A summaries) read it back without cross-layer imports.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_registered = False


def _on_card_completed(card_id: str, state: str, result: dict | None) -> None:
    """Card finished → aggregate the agent's tool usage into the registry."""
    try:
        from l3.services.counter import get_counter

        agent_id = str((result or {}).get("agent_id") or (result or {}).get("agent") or "")
        summary = get_counter().tool_summary(agent_id) if agent_id else get_counter().tool_summary()
        # success/failure counts live per-tool inside by_tool; aggregate them.
        by_tool = summary.get("by_tool", {})
        total = summary.get("total", 0)
        success = sum(int(t.get("success", 0)) for t in by_tool.values())
        snapshot = {
            "card_id": card_id,
            "state": state,
            "agent_id": agent_id,
            "ts": time.time(),
            "by_tool": by_tool,
            "total": total,
            "success": success,
        }
        from l1.kernel.registry import get_registry

        get_registry().set_section("card_tool_stats", snapshot)
        # Three-table linkage (card × tool × skill): skills named after the
        # completing card's tools gain a usage point. Non-fatal on failure.
        try:
            from l1.kernel.skill import get_skill_manager

            get_skill_manager().bump_usage_for_tools(list(by_tool.keys()))
        except Exception as e:
            logger.debug("card_tool_stats: skill bump skipped: %s", e)
        # 2.1-D6: card completion → structured build + review results. The
        # building result comes from the TieredCache L2 shared summary (HTN-B
        # surface); the review result from the review pipeline disposition.
        # Both are merged into the registry section for L3A / dashboards.
        try:
            from l3.memory.tiered_cache import get_tiered_cache
            from l3.services.review_pipeline import get_review_pipeline

            tc = get_tiered_cache()
            build_summary = tc.get_shared_summary(card_id, "build_summary") or {}
            review_disposition = get_review_pipeline().dispose(
                {"stats": build_summary}, rel_path=str((result or {}).get("path", "")), agent_id=agent_id
            )
            result_section = {
                "card_id": card_id,
                "build_result": {
                    "changed_lines": int(build_summary.get("changed_lines", 0) or 0),
                    "hunks": int(build_summary.get("hunks", 0) or 0),
                },
                "review_result": review_disposition,
            }
            get_registry().set_section("card_build_review", result_section)
        except Exception as e:
            logger.debug("card_tool_stats: build/review aggregation skipped: %s", e)
    except Exception as e:
        logger.debug("card_tool_stats: aggregation skipped: %s", e)


def wire_card_tool_stats() -> dict:
    """Register the card→tool-stats completion bridge (idempotent)."""
    global _registered
    if _registered:
        return {"success": True, "registered": True}
    try:
        from l3.card.card_registry import get_registry

        get_registry().register_completion_listener(_on_card_completed)
        _registered = True
        return {"success": True, "registered": True}
    except Exception as e:
        logger.warning("card_tool_stats: bridge registration failed: %s", e)
        return {"success": False, "error": str(e)}


def unregister_card_tool_stats() -> dict:
    """Detach the completion listener (idempotent)."""
    global _registered
    try:
        from l3.card.card_registry import get_registry

        get_registry().unregister_completion_listener(_on_card_completed)
    except Exception:
        pass
    _registered = False
    return {"success": True}


def reset_card_tool_stats() -> None:
    """Reset the registration flag (test isolation)."""
    global _registered
    _registered = False
