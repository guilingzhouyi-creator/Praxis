"""Memory refinery (Phase 3, M2) — classification → dedup → clean → score → refine → transform.

Pipeline over memory entries (R1-R4) produced by an Agent entity or Cell
domain:

  classify    — bucket by entry_type / tags / identity domain
  dedup       — drop duplicates (exact name or dedup_key prefix, never raw
                substring — mirrors the skill dedup rule)
  clean       — drop low-quality entries (extends _is_good_memory)
  score       — rank by MEMORY_RING_SCORE weights (tags/importance/tokens)
  refine      — promote high-value candidates (target ring uplift)
  transform   — convert to R5 modeling input (structured records)

Each stage is a pure function; ``run_pipeline`` composes them. All stages
degrade gracefully (empty lists, never raise).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from l1.kernel.params.system import (
    LOG_TRUNC_300,
    MEMORY_REFINE_REBURN_BOOST,
    MEMORY_REFINE_REBURN_MAX_SCORE,
    MEMORY_REFINERY_ENABLED_DEFAULT,
    MEMORY_RING_SCORE_HIGH_IMPORTANCE,
    MEMORY_RING_SCORE_MODERATE_IMPORTANCE,
    MEMORY_RING_SCORE_TAG_WEIGHT,
)

logger = logging.getLogger(__name__)

_DEDUP_PREFIX_SEP = "_"


class MemoryRefinery:
    """Memory purification pipeline (classify/dedup/clean/score/refine/transform)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._enabled = MEMORY_REFINERY_ENABLED_DEFAULT

    # ── Operator switch ──

    def set_enabled(self, enabled: bool) -> dict:
        """Set the write-path refinery switch (operator-controlled)."""
        with self._lock:
            self._enabled = bool(enabled)
        return {"success": True, "enabled": self._enabled}

    def status(self) -> dict:
        """Current refinery switch state."""
        with self._lock:
            return {"enabled": self._enabled}

    # ── Stage 1: classify ──

    def classify(self, entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Bucket entries by entry_type (unknown → 'other')."""
        buckets: dict[str, list[dict[str, Any]]] = {}
        for e in entries:
            key = str(e.get("entry_type") or "other")
            buckets.setdefault(key, []).append(e)
        return buckets

    # ── Stage 2: dedup ──

    def dedup(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop duplicates by exact name or dedup_key prefix (never substring).

        The dedup_key is the first line truncated to a canonical length; an
        entry is a duplicate when its content matches an already-seen key
        exactly, or continues it with a word boundary (``key + " "``) —
        never raw substring, so ``rm`` never swallows ``rmdir``.
        """
        seen: set[str] = set()
        kept: list[dict[str, Any]] = []
        for e in entries:
            content = str(e.get("content") or "")
            if not content:
                continue
            key = self._dedup_key(content)
            dup = key in seen or any(key.startswith(k + " ") for k in seen)
            if dup:
                continue
            seen.add(key)
            kept.append(e)
        return kept

    def _dedup_key(self, content: str, limit: int = 40) -> str:
        """Canonical dedup key: first token line truncated."""
        head = content.strip().splitlines()[0] if content.strip() else ""
        return head[:limit]

    # ── Stage 3: clean ──

    def clean(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop low-quality entries (extends the memory quality gate)."""
        try:
            from l3.memory.memory_quality import _is_good_memory

            return [
                e
                for e in entries
                if _is_good_memory(str(e.get("content") or ""), str(e.get("entry_type") or "note"))[0]
            ]
        except Exception as exc:
            logger.debug("memory_refinery: clean skipped: %s", exc)
            return entries

    # ── Stage 4: score ──

    def score(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Rank entries by MEMORY_RING_SCORE weights (tags/importance/tokens)."""
        scored: list[dict[str, Any]] = []
        for e in entries:
            s = float(e.get("importance", 0.0) or 0.0)
            s += len(e.get("tags") or []) * MEMORY_RING_SCORE_TAG_WEIGHT
            s += MEMORY_RING_SCORE_HIGH_IMPORTANCE if s > MEMORY_RING_SCORE_MODERATE_IMPORTANCE else 0.0
            out = dict(e)
            out["refinery_score"] = round(s, 3)
            scored.append(out)
        scored.sort(key=lambda x: x["refinery_score"], reverse=True)
        return scored

    # ── Stage 5: refine (promote candidates) ──

    def refine(self, scored: list[dict[str, Any]], target_ring: int = 3) -> list[dict[str, Any]]:
        """Mark high-value entries as promote candidates (ring uplift)."""
        for e in scored:
            e["promote_to_ring"] = (
                target_ring if e.get("refinery_score", 0.0) >= MEMORY_RING_SCORE_HIGH_IMPORTANCE else 0
            )
        return scored

    # ── Stage 5b: re-refine ("burn-back") — re-score edge-quality
    #    entries that clean() dropped, instead of losing them. ──

    def re_refine(
        self,
        cleaned: list[dict[str, Any]],
        dropped: list[dict[str, Any]],
        target_ring: int = 3,
    ) -> tuple[list[dict[str, Any]], int]:
        """Burn edge-quality entries back into the pipeline (re-refine).

        Entries clean() dropped (below the quality gate but not garbage) are
        re-scored with a small boost so accumulated evidence may lift them
        into the kept set; the boost is capped so re-refined entries never
        reach the promotion threshold by themselves.

        Args:
            cleaned: Entries that survived the clean() gate.
            dropped: Entries clean() rejected (edge-quality candidates).
            target_ring: Promotion target ring (unchanged from refine()).

        Returns:
            ``(kept, reburned)`` — the merged kept list and how many
            dropped entries were successfully burned back.
        """
        reburned = 0
        for e in dropped:
            base = float(e.get("importance", 0.0) or 0.0)
            base += len(e.get("tags") or []) * MEMORY_RING_SCORE_TAG_WEIGHT
            base += MEMORY_REFINE_REBURN_BOOST  # accumulated-evidence lift
            boosted = round(min(base, MEMORY_REFINE_REBURN_MAX_SCORE), 3)
            if boosted < MEMORY_RING_SCORE_HIGH_IMPORTANCE:
                continue
            out = dict(e)
            out["refinery_score"] = boosted
            out["promote_to_ring"] = target_ring if boosted >= MEMORY_RING_SCORE_HIGH_IMPORTANCE else 0
            cleaned.append(out)
            reburned += 1
        cleaned.sort(key=lambda x: x.get("refinery_score", 0.0), reverse=True)
        return cleaned, reburned

    # ── Stage 6: transform (R5 modeling input) ──

    def transform(self, refined: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert refined entries into structured R5 modeling records."""
        records = []
        for e in refined:
            records.append(
                {
                    "entry_id": e.get("id", ""),
                    "entry_type": e.get("entry_type", ""),
                    "cell_id": e.get("cell_id", ""),
                    "agent_id": e.get("agent_id", ""),
                    "tags": list(e.get("tags") or []),
                    "refinery_score": e.get("refinery_score", 0.0),
                    "promote_to_ring": e.get("promote_to_ring", 0),
                    "content": str(e.get("content") or "")[:LOG_TRUNC_300],
                }
            )
        return records

    # ── Full pipeline ──

    def run_pipeline(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Run all stages; returns stats + the transformed modeling records."""
        classified = self.classify(entries)
        all_entries = [e for bucket in classified.values() for e in bucket]
        deduped = self.dedup(all_entries)
        cleaned = self.clean(deduped)
        # Stage 5b (burn-back/re-refine): clean() dropped edge-quality entries are
        # burned back with an evidence boost instead of being lost. The kept
        # list carries the original objects, so dropped = not kept by identity.
        dropped = [e for e in deduped if not any(e is c for c in cleaned)]
        merged, reburned = self.re_refine(cleaned, dropped)
        scored = self.score(merged)
        refined = self.refine(scored)
        records = self.transform(refined)
        return {
            "success": True,
            "stats": {
                "input": len(entries),
                "deduped": len(all_entries) - len(deduped),
                "cleaned": len(dropped) - reburned,
                "reburned": reburned,
                "kept": len(records),
                "promoted": sum(1 for r in records if r["promote_to_ring"]),
            },
            "records": records,
        }


_refinery: MemoryRefinery | None = None
_refinery_lock = __import__("threading").Lock()


def get_refinery() -> MemoryRefinery:
    """Get the global MemoryRefinery singleton."""
    global _refinery
    if _refinery is None:
        with _refinery_lock:
            if _refinery is None:
                _refinery = MemoryRefinery()
    return _refinery


def reset_refinery() -> None:
    """Reset the singleton (used by tests)."""
    global _refinery
    with _refinery_lock:
        _refinery = None


def refine_and_persist(entries: list[dict[str, Any]]) -> dict:
    """Production entry: run the refinery pipeline and persist records (M2/M4).

    Runs ``run_pipeline`` over the given entries (e.g. freshly written
    memory) and appends the transformed records to the TieredCache L3
    archive index ``memory:refined_records`` — the data source the RC
    memory record source (M4) reads for query/stats/corpus export.

    Gated by the operator switch (``set_enabled``); disabled → no-op.
    Degrades gracefully (never raises).

    Returns:
        ``{"success": bool, "persisted": N, "stats": {...}}``.
    """
    try:
        r = get_refinery()
        if not r.status().get("enabled"):
            return {"success": False, "persisted": 0, "reason": "refinery disabled"}
        result = r.run_pipeline(entries)
        records = result.get("records") or []
        if not records:
            return {"success": True, "persisted": 0, "stats": result.get("stats")}
        from l3.memory.tiered_cache import get_tiered_cache

        tc = get_tiered_cache()
        meta = tc.get_archive_index("memory:refined_records") or {}
        existing = list(meta.get("records", []) or [])
        existing.extend(records)
        meta["records"] = existing
        tc.index_archive("memory:refined_records", meta)
        # Phase 3 M3: supply the refined records to downstream consumers
        # (R5 graph edges + skill system input). Never blocks the write path.
        try:
            from l3.memory.memory_supply_chain import supply_after_refine

            supply_after_refine(records)
        except Exception as e:
            logger.debug("memory_refinery: supply after refine skipped: %s", e)
        return {"success": True, "persisted": len(records), "stats": result.get("stats")}
    except Exception as e:
        logger.debug("memory_refinery: refine_and_persist skipped: %s", e)
        return {"success": False, "persisted": 0, "error": str(e)}
