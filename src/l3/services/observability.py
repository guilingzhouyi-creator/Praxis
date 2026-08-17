"""Best-effort unified metrics for cross-layer performance and quality signals."""

from __future__ import annotations

import logging
import math
import time
from typing import Any

logger = logging.getLogger(__name__)

# Keep dimensions bounded and consistent across the toolchain.  Payloads,
# target URLs, evidence ids, and error text are intentionally excluded.
_STANDARD_TAGS = frozenset(
    {
        "cell",
        "agent",
        "card",
        "tool",
        "mode",
        "edge_mode",
        "source",
        "success",
        "status",
        "phase",
        "relation",
    }
)


def normalize_tags(tags: dict[str, Any] | None = None) -> dict[str, str]:
    """Return the bounded, string-valued tag set used by all new metrics."""
    return {
        str(key): str(value)
        for key, value in (tags or {}).items()
        if str(key) in _STANDARD_TAGS and value is not None and str(value) != ""
    }


def emit_metric(
    name: str,
    value: float,
    *,
    tags: dict[str, Any] | None = None,
    metric_type: str = "gauge",
) -> None:
    """Ingest one normalized metric point without raising into the caller."""
    try:
        numeric = float(value)
        if not math.isfinite(numeric):
            return
        from l3.services.stats_center import MetricPoint, get_center

        get_center().ingest(
            MetricPoint(
                name=str(name),
                value=numeric,
                tags=normalize_tags(tags),
                timestamp=time.time(),
                metric_type=metric_type,
            )
        )
    except Exception:
        logger.debug("observability: metric ingest skipped", exc_info=True)


def emit_duration(
    name: str,
    started: float,
    *,
    tags: dict[str, Any] | None = None,
) -> None:
    """Record elapsed milliseconds from a ``perf_counter`` start value."""
    emit_metric(name, (time.perf_counter() - started) * 1000.0, tags=tags, metric_type="gauge")


def emit_count(name: str, value: int = 1, *, tags: dict[str, Any] | None = None) -> None:
    """Record a counter value using the shared metric type and tag policy."""
    emit_metric(name, float(value), tags=tags, metric_type="counter")


__all__ = ["emit_count", "emit_duration", "emit_metric", "normalize_tags"]
