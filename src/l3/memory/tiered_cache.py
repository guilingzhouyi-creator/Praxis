"""TieredCache — three-layer cross-cell cache architecture (2.1-D2).

Layers:
  L1 — this Cell's hot zone: per-Cell recent reads (same semantics as
       IsolatedCache, but kept in this module for a single cache surface).
  L2 — Cell-to-Cell shared summaries: cross-Cell index that HTN-B reads
       (only this tier is consulted across Cells; never the full files).
  L3 — cross-Cell archive index: heavy/old entries, largest capacity,
       longest TTL; eviction (oldest-first) at capacity.

All layers are thread-safe and degrade gracefully — a missing layer entry
returns None, never raises. Capacity/TTL are params constants; a deployment
may override via the usual discovery/config surface.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from l1.kernel.params.system import (
    TIERED_CACHE_L1_MAX_ENTRIES,
    TIERED_CACHE_L1_TTL,
    TIERED_CACHE_L2_MAX_ENTRIES,
    TIERED_CACHE_L2_TTL,
    TIERED_CACHE_L3_MAX_ENTRIES,
    TIERED_CACHE_L3_TTL,
)

logger = logging.getLogger(__name__)

_tiered_lock = threading.RLock()
_tiered: TieredCache | None = None


class TieredCache:
    """Three-layer cache: per-cell hot zone + cross-cell summary + archive index."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._layers: dict[str, dict[str, tuple[Any, float]]] = {
            "L1": {},  # this-Cell hot zone
            "L2": {},  # Cell-to-Cell shared summaries
            "L3": {},  # cross-Cell archive index
        }
        self._limits: dict[str, int] = {
            "L1": TIERED_CACHE_L1_MAX_ENTRIES,
            "L2": TIERED_CACHE_L2_MAX_ENTRIES,
            "L3": TIERED_CACHE_L3_MAX_ENTRIES,
        }
        self._ttls: dict[str, float] = {
            "L1": TIERED_CACHE_L1_TTL,
            "L2": TIERED_CACHE_L2_TTL,
            "L3": TIERED_CACHE_L3_TTL,
        }

    # ── Core ops ──

    def set(self, layer: str, key: str, value: Any) -> bool:
        """Store a value in a layer (LRU-ish: oldest evicted at capacity)."""
        layer = layer.upper()
        if layer not in self._layers:
            return False
        with self._lock:
            bucket = self._layers[layer]
            bucket[key] = (value, time.time())
            limit = self._limits[layer]
            if len(bucket) > limit:
                # Evict oldest by insertion time (simple FIFO fallback).
                oldest = min(bucket, key=lambda k: bucket[k][1])
                bucket.pop(oldest, None)
        return True

    def get(self, layer: str, key: str) -> Any:
        """Read a value; expired/missing entries return None."""
        layer = layer.upper()
        if layer not in self._layers:
            return None
        with self._lock:
            item = self._layers[layer].get(key)
            if item is None:
                return None
            value, ts = item
            if time.time() - ts > self._ttls[layer]:
                self._layers[layer].pop(key, None)
                return None
            return value

    def invalidate(self, layer: str, key: str) -> bool:
        """Drop one key from a layer."""
        layer = layer.upper()
        with self._lock:
            return self._layers.get(layer, {}).pop(key, None) is not None

    def clear(self) -> None:
        """Drop all layers (tests / lifecycle)."""
        with self._lock:
            for bucket in self._layers.values():
                bucket.clear()

    # ── Cross-cell surface (L2) ──

    def set_shared_summary(self, cell_id: str, key: str, summary: Any) -> bool:
        """Write a Cell-to-Cell shared summary into L2 (HTN-B reads this)."""
        return self.set("L2", f"{cell_id}::{key}", summary)

    def get_shared_summary(self, cell_id: str, key: str) -> Any:
        """Read a cross-Cell shared summary from L2."""
        return self.get("L2", f"{cell_id}::{key}")

    # ── Archive index (L3) ──

    def index_archive(self, key: str, meta: Any) -> bool:
        """Write a cross-Cell archive index entry into L3."""
        return self.set("L3", key, meta)

    def get_archive_index(self, key: str) -> Any:
        """Read a cross-Cell archive index entry from L3."""
        return self.get("L3", key)

    # ── Stats ──

    def stats(self) -> dict:
        """Per-layer entry counts (for status surfaces)."""
        with self._lock:
            return {
                layer: {
                    "entries": len(bucket),
                    "capacity": self._limits[layer],
                    "ttl": self._ttls[layer],
                }
                for layer, bucket in self._layers.items()
            }


def get_tiered_cache() -> TieredCache:
    """Get the global TieredCache singleton."""
    global _tiered
    with _tiered_lock:
        if _tiered is None:
            _tiered = TieredCache()
        return _tiered


def reset_tiered_cache() -> None:
    """Reset the singleton (used by tests)."""
    global _tiered
    with _tiered_lock:
        _tiered = None
