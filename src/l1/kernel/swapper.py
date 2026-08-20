"""Swapping daemon — background memory pressure management.

Moves entries between working/short/long-term memory rings:
  _swap_out_working: ring1 -> ring2/ring3 (on pressure)
  _compact_short_term: ring2 -> ring3 (periodic)
  swap_in: ring3 -> ring1 (on access miss, reversing swap_out)

Design doc promises bidirectional swap but only _swap_out existed.
swap_in() is the missing reverse direction — restores cold data on demand.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from l1.kernel.params.system import LOG_TRUNC_100

from .allocator import get_allocator
from .params.kernel import (
    SWAPPER_COMPACT_IMPORTANCE,
    SWAPPER_DEFAULT_INTERVAL,
    SWAPPER_PRESSURE_HIGH,
    SWAPPER_PRESSURE_LOW,
    SWAPPER_SWAP_COUNT,
    SWAPPER_SWAP_OUT_IMPORTANCE,
)

logger = logging.getLogger(__name__)


def plan_swap_out(
    entries: list[dict], count: int | None = None, importance_threshold: float = SWAPPER_SWAP_OUT_IMPORTANCE
) -> list[dict]:
    """Plan working-ring destinations from explicit entry facts."""
    limit = SWAPPER_SWAP_COUNT if count is None else max(0, count)
    return [
        {"id": entry["id"], "target_ring": 3 if entry["importance"] < importance_threshold else 2}
        for entry in entries[:limit]
    ]


def plan_compaction(entries: list[dict], importance_threshold: float = SWAPPER_COMPACT_IMPORTANCE) -> list[dict]:
    """Plan ring-2 to ring-3 moves for expired low-importance entries."""
    return [
        {"id": entry["id"], "target_ring": 3}
        for entry in entries
        if entry["importance"] < importance_threshold and entry["ttl"] > 0 and entry["expired"]
    ]


def plan_pressure(snapshot: dict, high_threshold: float = SWAPPER_PRESSURE_HIGH) -> dict[str, bool]:
    """Plan pressure actions from explicit occupancy percentages."""
    if not snapshot["under_pressure"]:
        return {"swap_out_working": False, "compact_short_term": False, "long_term_full": False}
    return {
        "swap_out_working": snapshot["working_pct"] >= high_threshold,
        "compact_short_term": snapshot["short_pct"] >= high_threshold,
        "long_term_full": snapshot["long_pct"] >= high_threshold,
    }


class Swapper:
    """Background memory pressure manager."""

    def __init__(self, interval: float = SWAPPER_DEFAULT_INTERVAL, memory_service=None):
        self.interval = interval
        self._running = True
        self._mem = memory_service
        self._thread: threading.Thread | None = None
        self._total_swapped_out = 0
        self._total_compactions = 0

    def set_memory(self, mem: Any) -> None:
        """Wire MemoryService to the swapper (called from boot.py).  Idempotent."""
        if self._mem is not None and self._thread and self._thread.is_alive():
            logger.warning("swapper already wired, skipping duplicate set_memory")
            return
        self._mem = mem
        logger.info("swapper wired to memory service")
        self._alloc = get_allocator()
        self._total_swapped_out = 0
        self._total_compactions = 0
        self._pager_bridge = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("swapper started (interval=%ds)", self.interval)

    def _loop(self) -> None:
        while self._running:
            time.sleep(self.interval)
            try:
                self._tick()
            except Exception as e:
                logger.error("swapper tick error: %s", e)

    def _tick(self) -> None:
        stats = self._mem.stats()
        pressure = self._alloc.pressure(threshold=SWAPPER_PRESSURE_LOW)
        if not pressure["under_pressure"]:
            return
        w_pct = stats["working"]["pct"]
        s_pct = stats["short"]["pct"]
        l_pct = stats["long"]["pct"]
        logger.info("pressure: W=%d%% S=%d%% L=%d%%", w_pct, s_pct, l_pct)
        plan = plan_pressure({"under_pressure": True, "working_pct": w_pct, "short_pct": s_pct, "long_pct": l_pct})
        if plan["swap_out_working"]:
            n = self._swap_out_working()
            logger.warning("swapped out %d entries from working memory", n)
        if plan["compact_short_term"]:
            n = self._compact_short_term()
            logger.warning("compacted %d short-term entries", n)
        if plan["long_term_full"]:
            logger.warning("LONG-TERM MEMORY FULL")

    def swap_in(self, entry_id: str) -> dict:
        """Restore a swapped-out entry from long-term back to working set."""
        if not self._mem:
            return {"success": False, "error": "no memory service"}
        try:
            # Directed id lookup (early-exit scan) — avoids building/sorting
            # the full recall list just to find one entry.
            entry = self._mem.get_entry(entry_id)
            if not entry:
                return {"success": False, "error": f"entry not found: {entry_id}"}

            # Preserve all original metadata for the restore
            new_id = self._mem.remember(
                agent_id=entry.agent_id,
                entry_type=entry.entry_type,
                content=entry.content,
                tags=entry.tags,
                source=entry.source,
                importance=entry.importance,
                cell_id=entry.cell_id,
                ring=1,
            )
            self._total_swapped_out -= 1
            return {
                "success": True,
                "entry": {
                    "id": new_id,
                    "agent_id": entry.agent_id,
                    "entry_type": entry.entry_type,
                    "content": entry.content[:LOG_TRUNC_100],
                    "cell_id": entry.cell_id,
                    "importance": entry.importance,
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _swap_out_working(self, count: int = SWAPPER_SWAP_COUNT) -> int:
        if not self._mem or not hasattr(self._mem, "working"):
            return 0
        entries = self._mem.working_entries()[:count]
        by_id = {e.id: e for e in entries}
        actions = plan_swap_out([{"id": e.id, "importance": e.importance} for e in entries], count=count)
        for action in actions:
            e = by_id[action["id"]]
            try:
                self._mem.promote(e.id, target_ring=action["target_ring"])
                self._total_swapped_out += 1
                logger.debug("swapped %s ring1 → ring%d (importance=%.2f)", e.id, action["target_ring"], e.importance)
            except Exception as err:
                logger.warning("swap out %s failed: %s", getattr(e, "id", "?"), err)
        return len(entries)

    def _compact_short_term(self) -> int:
        if not self._mem or not hasattr(self._mem, "short_term"):
            return 0
        entries = self._mem.short_term()
        candidates = []
        by_id = {e.id: e for e in entries}
        for e in entries:
            try:
                expired = e.expired() if e.importance < SWAPPER_COMPACT_IMPORTANCE and e.ttl > 0 else False
                candidates.append({"id": e.id, "importance": e.importance, "ttl": e.ttl, "expired": expired})
            except Exception as err:
                logger.warning("compact %s failed: %s", getattr(e, "id", "?"), err)
        actions = plan_compaction(candidates)
        compacted = 0
        for action in actions:
            e = by_id[action["id"]]
            try:
                self._mem.promote(e.id, target_ring=action["target_ring"])
                compacted += 1
                self._total_compactions += 1
                logger.debug("compacted %s ring2 → ring3", e.id)
            except Exception as err:
                logger.warning("compact %s failed: %s", getattr(e, "id", "?"), err)
        return compacted

    def stop(self) -> None:
        """Stop the background swap loop."""
        self._running = False

    def stats(self) -> dict:
        """Return swap statistics (swapped_out, compactions)."""
        return {"swapped_out": getattr(self, "_total_swapped_out", 0), "compactions": self._total_compactions}


_swapper: Swapper | None = None
_swapper_lock = threading.Lock()


def get_swapper(interval: float = SWAPPER_DEFAULT_INTERVAL, memory_service=None) -> Swapper:
    """Get the swapper singleton (lazily created)."""
    global _swapper
    if _swapper is None:
        with _swapper_lock:
            if _swapper is None:
                _swapper = Swapper(interval, memory_service)
    return _swapper


def reset_swapper() -> None:
    """Reset the swapper singleton, stopping it first (for tests / hot reset)."""
    global _swapper
    if _swapper:
        _swapper.stop()
    _swapper = None
