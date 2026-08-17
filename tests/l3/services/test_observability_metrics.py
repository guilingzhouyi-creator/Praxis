"""Regression tests for the unified cross-link metric contract."""

from __future__ import annotations

from l3.services.observability import emit_metric, normalize_tags
from l3.services.stats_center import get_center, reset_center


def test_normalize_tags_keeps_only_bounded_dimensions() -> None:
    """High-cardinality payload fields must not enter the metric tag set."""
    assert normalize_tags({"tool": "scan", "cell": "c1", "raw": "payload", "target": "url"}) == {
        "tool": "scan",
        "cell": "c1",
    }


def test_emit_metric_reaches_stats_center_with_standard_tags() -> None:
    """Metric helpers must use StatsCenter and preserve canonical dimensions."""
    reset_center()
    try:
        emit_metric(
            "tool_registry.register.duration_ms",
            2.5,
            tags={"tool": "scan", "cell": "c1", "agent": "a1", "raw": "ignored"},
        )
        rows = get_center().query(metrics=["tool_registry.register.duration_ms"], window="all", agg="last")
        assert len(rows) == 1
        assert "agent=a1" in rows[0]["tags_key"]
        assert "cell=c1" in rows[0]["tags_key"]
        assert "raw=" not in rows[0]["tags_key"]
    finally:
        reset_center()
