"""Boot step — register the L3 string-event schema (W4.3)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Curated catalog of string events emitted across L3 buses. Kernel owns the
# registry; each owner registers its own names so unknown events are visible
# instead of silently untyped.
_L3_EVENT_CATALOG: list[tuple[str, str, str]] = [
    ("error_log", "l3.error_bus", "error bus entry emitted for a component"),
    ("auto_test.result", "l3.tool_system.auto_test", "auto-test verdict published"),
    ("engineering_debug_mode_changed", "l3.tool_system.engineering_debug", "debug mode toggled"),
    ("security_mode_change", "l3.tool_system.security_mode", "security mode switched"),
    ("security_mode_warning", "l3.tool_system.security_mode", "attack confirmation required"),
    ("agent.turn_complete", "l3.services.hook", "agent turn finished"),
    ("agent.loop_error", "l3.services.hook", "agent loop raised"),
    ("agent.session_end", "l3.services.hook", "agent session closed"),
    ("stats.memory.mer.switch", "l3.memory.memory_mer", "mer ring toggled"),
    ("stats.memory.graph.switch", "l3.memory.memory_graph", "graph memory toggled"),
    ("review_rework_requested", "l3.services.review_pipeline", "directed rework issued"),
    ("discussion.completed", "l3.discussion.issue_orchestrator", "discussion session completed"),
    ("discussion.report", "l3.discussion.report_service", "discussion report published"),
    ("skill_mutated", "l1.kernel.skill", "skill file mutated"),
]


def _register_event_schema() -> dict:
    """Register the L3 string-event catalog into the kernel schema registry."""
    try:
        from l1.kernel.schema import register_event

        loaded = 0
        for name, owner, description in _L3_EVENT_CATALOG:
            if register_event(name, owner, description):
                loaded += 1
        logger.info("event schema: registered %d/%d L3 events", loaded, len(_L3_EVENT_CATALOG))
        return {"success": True, "registered": loaded, "catalog": len(_L3_EVENT_CATALOG)}
    except Exception as e:
        logger.warning("event schema: registration failed: %s", e)
        return {"success": False, "error": str(e)}
