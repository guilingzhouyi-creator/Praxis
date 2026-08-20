"""L2 Shell: statistics commands.

Extracted from ``extra.py`` (per-domain split).  Owns the StatsCenter /
card timeline / memory-graph query commands.
"""

from __future__ import annotations

import logging

from l1.kernel.params.system import STATS_TIMELINE_LIMIT, STATS_TOP_LIMIT
from l2.i18n import t as _t

logger = logging.getLogger(__name__)


def _stats_summary() -> dict:
    """Stats overview: event-bus counters + StatsCenter summary."""
    try:
        from l1.kernel import get_event_bus

        bus_stats = get_event_bus().stats()
    except Exception:
        bus_stats = {}
    from l2.bridge import stats_center

    try:
        summary = stats_center().stats()
    except Exception:
        summary = {}
    return {"success": True, "event_bus": bus_stats, "metrics": summary}


def _stats_timeline(args: list[str], window: str) -> dict:
    """Card end-to-end timeline (cell + agent breakdown)."""
    from l2.bridge import card_registry

    limit = STATS_TIMELINE_LIMIT
    for a in args[1:]:
        if a.isdigit():
            limit = int(a)
            break
    return {"success": True, **card_registry().execution_stats(limit=limit)}


def _stats_query(window: str, metrics: list[str] | None) -> dict:
    """Query StatsCenter aggregated metrics within a window (None = all)."""
    from l2.bridge import stats_center

    return {"success": True, "metrics": stats_center().query(metrics=metrics, window=window)}


def _stats_graph(args: list[str], window: str) -> dict:
    """Memory-graph overview: enabled/edge mode/stats/semantic edges/compact."""
    from l2.bridge import memory_graph

    g = memory_graph()
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


def _stats_top(args: list[str], window: str) -> dict:
    """Cross-Cell ranking for a metric."""
    metric = args[1] if len(args) > 1 else "card.execution.total"
    from l2.bridge import stats_center

    return {
        "success": True,
        "metric": metric,
        "ranking": stats_center().top(metric, limit=STATS_TOP_LIMIT, window=window),
    }


_STATS_METRIC_GROUPS: dict[str, list[str]] = {
    "api": ["api.request.latency", "api.request.count"],
    "side": [
        "agent.loop.side.compression",
        "agent.loop.side.parallel_read",
        "agent.loop.side.continuation",
        "agent.loop.side.llm_tools",
    ],
    "reasoning": [
        "l3a.tokens.reasoning",
        "card.execution.total",
        "card.execution.cell",
        "card.execution.agent",
    ],
}


def _cmd_stats(args: list[str], session=None) -> dict:
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
        return _stats_summary()
    if sub == "timeline":
        return _stats_timeline(args, window)
    if sub == "graph":
        return _stats_graph(args, window)
    if sub == "top":
        return _stats_top(args, window)
    if sub in _STATS_METRIC_GROUPS or sub in ("tools", "compression", "cell", "agent", "cells"):
        return _stats_query(window, _STATS_METRIC_GROUPS.get(sub))
    return {
        "success": False,
        "error": _t("shell.app_error.usage_stats"),
    }
