"""L2 Shell: statistics commands.

Extracted from ``extra.py`` (per-domain split).  Owns the StatsCenter /
card timeline / memory-graph query commands.
"""

from __future__ import annotations

import logging

from l1.kernel.params.system import STATS_TIMELINE_LIMIT, STATS_TOP_LIMIT
from l2.i18n import t as _t

logger = logging.getLogger(__name__)


def _cmd_stats(args: list[str]) -> dict:
    """Query statistics: StatsCenter metrics, card execution timeline,
    side-execution timing, API request timing, reasoning token spend.

    Sub-commands:
      timeline [limit]            card end-to-end timeline (cell + agent breakdown)
      api                         API request latency/count (stats.api.request)
      side [window]               AgentLoop side-execution timing
      reasoning [window]          deliberation costs (reasoning tokens + card exec)
      top <metric> [window]       cross-Cell ranking for a metric
      <tools|compression|cell|agent|cells> [window]   generic StatsCenter query
    """
    sub = args[0].lower() if args else ""
    window = "5m"
    for a in args[1:]:
        if a in ("1m", "5m", "1h", "all"):
            window = a
            break

    if not sub:
        try:
            from l1.kernel import get_event_bus

            bus_stats = get_event_bus().stats()
        except Exception:
            bus_stats = {}
        from l3.services.stats_center import get_center as _sc

        try:
            summary = _sc().stats()
        except Exception:
            summary = {}
        return {"success": True, "event_bus": bus_stats, "metrics": summary}

    if sub == "timeline":
        from l3.card.card_registry import get_registry

        limit = STATS_TIMELINE_LIMIT
        for a in args[1:]:
            if a.isdigit():
                limit = int(a)
                break
        return {"success": True, **get_registry().execution_stats(limit=limit)}

    if sub == "api":
        from l3.services.stats_center import get_center as _sc

        return {
            "success": True,
            "metrics": _sc().query(metrics=["api.request.latency", "api.request.count"], window=window),
        }

    if sub == "side":
        from l3.services.stats_center import get_center as _sc

        return {
            "success": True,
            "metrics": _sc().query(
                metrics=[
                    "agent.loop.side.compression",
                    "agent.loop.side.parallel_read",
                    "agent.loop.side.continuation",
                    "agent.loop.side.llm_tools",
                ],
                window=window,
            ),
        }

    if sub == "reasoning":
        from l3.services.stats_center import get_center as _sc

        return {
            "success": True,
            "metrics": _sc().query(
                metrics=["l3a.tokens.reasoning", "card.execution.total", "card.execution.cell", "card.execution.agent"],
                window=window,
            ),
        }

    if sub == "graph":
        from l3.memory.memory_graph import get_graph

        g = get_graph()
        return {
            "success": True,
            "graph": {
                "enabled": g.enabled,
                "edge_mode": g.edge_mode,
                "stats": g.stats(),
                "semantic": g.semantic_edges(limit=20),
                "compact": g.compact_report(min_degree=2),
            },
        }

    if sub == "top":
        metric = args[1] if len(args) > 1 else "card.execution.total"
        from l3.services.stats_center import get_center as _sc

        return {"success": True, "metric": metric, "ranking": _sc().top(metric, limit=STATS_TOP_LIMIT, window=window)}

    if sub in ("tools", "compression", "cell", "agent", "cells"):
        from l3.services.stats_center import get_center as _sc

        return {"success": True, "metrics": _sc().query(window=window)}

    return {
        "success": False,
        "error": _t("shell.app_error.usage_stats"),
    }
