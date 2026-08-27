"""Diff RC record source (2.1-D7) — line-precise relevance records.

Registers a ``diff`` source with the RecordCenter so query/stats/export
cover reviewed diffs. Each hunk contributes a line-precise record:

    {path, line_start, line_end, added_lines, removed_lines, score, reviewed}

The score weights added/removed lines (params constants) and applies a
reviewed bonus; it is capped per hunk. Consumers (memory, training-corpus
aggregation) read these records through the RecordCenter query surface.
"""

from __future__ import annotations

import logging
import time

from l4.params import (
    DIFF_LINE_SCORE_ADDED_WEIGHT,
    DIFF_LINE_SCORE_MAX_PER_HUNK,
    DIFF_LINE_SCORE_REMOVED_WEIGHT,
    DIFF_LINE_SCORE_REVIEWED_WEIGHT,
)

logger = logging.getLogger(__name__)


def line_score_for_hunk(hunk: dict, reviewed: bool = True) -> float:
    """Compute the line-precise relevance score for one diff hunk.

    Args:
        hunk: A sandbox_diff hunk dict (added_lines / removed_lines).
        reviewed: Whether the hunk went through the review pipeline.

    Returns:
        Relevance score, capped at DIFF_LINE_SCORE_MAX_PER_HUNK.
    """
    added = len(hunk.get("added_lines", []) or [])
    removed = len(hunk.get("removed_lines", []) or [])
    score = added * DIFF_LINE_SCORE_ADDED_WEIGHT + removed * DIFF_LINE_SCORE_REMOVED_WEIGHT
    if reviewed:
        score *= DIFF_LINE_SCORE_REVIEWED_WEIGHT
    return min(score, DIFF_LINE_SCORE_MAX_PER_HUNK)


def build_line_records(path: str, hunks: list[dict], reviewed: bool = True) -> list[dict]:
    """Build line-precise records for a diff's hunks.

    Args:
        path: File path the hunks belong to.
        hunks: List of sandbox_diff hunk dicts.
        reviewed: Whether the review pipeline saw these hunks.

    Returns:
        List of ``{path, line_start, line_end, added_lines, removed_lines,
        score, reviewed, ts}`` records (one per hunk).
    """
    records = []
    for hunk in hunks or []:
        start = int(hunk.get("modified_start", 0) or hunk.get("original_start", 0) or 0)
        end = int(hunk.get("modified_end", 0) or hunk.get("original_end", 0) or start)
        records.append(
            {
                "path": path,
                "line_start": start,
                "line_end": end,
                "added_lines": len(hunk.get("added_lines", []) or []),
                "removed_lines": len(hunk.get("removed_lines", []) or []),
                "score": line_score_for_hunk(hunk, reviewed=reviewed),
                "reviewed": reviewed,
                "ts": time.time(),
            }
        )
    return records


# ── RecordCenter source callables ──────────────────────────────────────────


def _query(limit: int = 0, since: float = 0.0, **kwargs) -> list[dict]:
    """Query recent diff line records (from the TieredCache L3 archive)."""
    try:
        from l3.memory.tiered_cache import get_tiered_cache

        tc = get_tiered_cache()
        meta = tc.get_archive_index("diff:line_records") or {}
        records = list(meta.get("records", []) or [])
        if since:
            records = [r for r in records if r.get("ts", 0) >= since]
        if limit > 0:
            records = records[:limit]
        return records
    except Exception as e:
        logger.debug("diff_record_source: query skipped: %s", e)
        return []


def _stats() -> dict:
    """Aggregate stats over the recorded diff line records."""
    records = _query()
    return {
        "diff_records": len(records),
        "total_score": round(sum(r.get("score", 0.0) for r in records), 3),
        "reviewed": sum(1 for r in records if r.get("reviewed")),
    }


def _export(limit: int = 0) -> list[dict]:
    """Export line-precise records (for corpus aggregation)."""
    return _query(limit=limit)


def register_diff_source() -> dict:
    """Register the ``diff`` record source with the RecordCenter (idempotent)."""
    try:
        from l3.services.record_center import get_record_center

        get_record_center().register_source(
            "diff",
            query_fn=_query,
            stats_fn=_stats,
            export_fn=_export,
        )
        return {"success": True}
    except Exception as e:
        logger.warning("diff_record_source: register skipped: %s", e)
        return {"success": False, "error": str(e)}
