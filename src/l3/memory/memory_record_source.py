"""Memory RC record source (Phase 3, M4) — refined memory → RecordCenter.

Registers a ``memory`` source with the RecordCenter so query/stats/export
cover purified memory. The export path produces **correction corpus** for
external training: refined memory + identity/Cell-domain features + log
context, ready for downstream model-correction fine-tuning.

All consumers degrade gracefully (never raise).
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _refined_records(limit: int = 0) -> list[dict[str, Any]]:
    """Pull refined memory records (from the refinery pipeline's last run)."""
    try:
        from l3.memory.tiered_cache import get_tiered_cache

        tc = get_tiered_cache()
        meta = tc.get_archive_index("memory:refined_records") or {}
        records = list(meta.get("records", []) or [])
        if limit > 0:
            records = records[:limit]
        return records
    except Exception as e:
        logger.debug("memory_record_source: records load skipped: %s", e)
        return []


def _query(limit: int = 0, since: float = 0.0, **kwargs) -> list[dict[str, Any]]:
    """Query recent refined-memory records."""
    records = _refined_records(limit=limit)
    if since:
        records = [r for r in records if r.get("ts", 0) >= since]
    return records


def _stats() -> dict:
    """Aggregate stats over refined-memory records."""
    records = _refined_records()
    return {
        "memory_records": len(records),
        "domains": sorted({r.get("cell_id", "") for r in records}),
        "types": sorted({r.get("entry_type", "") for r in records}),
    }


def _log_context(limit: int = 5) -> list[dict]:
    """Snapshot recent event-bus history as log context for the corpus.

    Each sample is a signal dict (type/source/data/timestamp) — the log
    side of the correction signal. Degrades to [] when unavailable.
    """
    try:
        from l1.kernel.event import get_bus

        return get_bus().history(limit=limit)
    except Exception as e:
        logger.debug("memory_record_source: log context skipped: %s", e)
        return []


def _export(limit: int = 0) -> list[dict[str, Any]]:
    """Export correction corpus: refined memory + identity/domain features + logs.

    Each sample combines the purified content with the producing
    identity/Cell-domain context and a recent event-bus log snapshot —
    the training-correction signal.
    """
    logs = _log_context()
    samples = []
    for rec in _refined_records(limit=limit):
        samples.append(
            {
                "content": rec.get("content", ""),
                "entry_type": rec.get("entry_type", ""),
                "cell_id": rec.get("cell_id", ""),
                "agent_id": rec.get("agent_id", ""),
                "identity_tags": rec.get("tags", []),
                "refinery_score": rec.get("refinery_score", 0.0),
                "log_context": logs,
                "ts": rec.get("ts", time.time()),
            }
        )
    return samples


def register_memory_source() -> dict:
    """Register the ``memory`` record source with the RecordCenter (idempotent)."""
    try:
        from l3.services.record_center import get_record_center

        get_record_center().register_source(
            "memory",
            query_fn=_query,
            stats_fn=_stats,
            export_fn=_export,
        )
        return {"success": True}
    except Exception as e:
        logger.warning("memory_record_source: register skipped: %s", e)
        return {"success": False, "error": str(e)}


def export_corpus(limit: int = 0) -> dict:
    """Public API/L2 surface for the M4 correction-corpus export.

    Wraps the private ``_export`` so the /api/v2/memory/corpus endpoint and
    the L2 ``/memory corpus`` command can hand refined memory + identity /
    Cell-domain context + log snapshots to external training tooling.

    Args:
        limit: max samples (0 = default).

    Returns:
        dict with success flag, sample count, and the corpus samples.
    """
    try:
        samples = _export(limit=limit)
        return {"success": True, "count": len(samples), "samples": samples}
    except Exception as e:
        logger.debug("memory_record_source: corpus export failed: %s", e)
        return {"success": False, "error": str(e)}
