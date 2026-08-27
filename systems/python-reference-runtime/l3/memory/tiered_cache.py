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

import json
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
        # P1.1: per-layer eviction/expiry/hit telemetry (persisted with save).
        self._metrics: dict[str, dict[str, int]] = {
            layer: {"hits": 0, "misses": 0, "expired": 0, "evictions": 0} for layer in self._layers
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
                self._metrics[layer]["evictions"] += 1
        return True

    def get(self, layer: str, key: str) -> Any:
        """Read a value; expired/missing entries return None."""
        layer = layer.upper()
        if layer not in self._layers:
            return None
        with self._lock:
            item = self._layers[layer].get(key)
            if item is None:
                self._metrics[layer]["misses"] += 1
                return None
            value, ts = item
            if time.time() - ts > self._ttls[layer]:
                self._layers[layer].pop(key, None)
                self._metrics[layer]["expired"] += 1
                return None
            self._metrics[layer]["hits"] += 1
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

    def keys(self, layer: str) -> list[str]:
        """Return the live keys of one layer (snapshot, thread-safe).

        Consumers that need to scan a namespace (e.g. a per-Cell program
        cache) use this instead of reaching into ``_layers`` directly.

        Args:
            layer: layer name ("L1" / "L2" / "L3").

        Returns:
            Snapshot list of the layer's current keys; empty for unknown layer.
        """
        layer = layer.upper()
        if layer not in self._layers:
            return []
        with self._lock:
            return list(self._layers[layer].keys())

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
        """Per-layer entry counts + P1.1 eviction/expiry/hit telemetry."""
        with self._lock:
            return {
                layer: {
                    "entries": len(bucket),
                    "capacity": self._limits[layer],
                    "ttl": self._ttls[layer],
                    **self._metrics[layer],
                }
                for layer, bucket in self._layers.items()
            }

    # ── Persistence interface (3.3, P1.1) ──

    def _default_store(self) -> Any:
        from pathlib import Path

        from l1.kernel.paths import data_dir as _data_dir
        from l3.durable_store import DurableJsonStore

        return DurableJsonStore(Path(_data_dir()) / "l3a" / "tiered_cache.json", kind="tiered_cache")

    def save(self, path: str | None = None) -> dict:
        """Persist all layers + telemetry through DurableJsonStore (P1.1).

        Non-JSON-serializable values are stringified best-effort and counted
        as ``lossy`` in the result — the mirror never blocks the hot path.
        """
        from pathlib import Path

        from l3.durable_store import DurableJsonStore

        store = DurableJsonStore(Path(path)) if path else self._default_store()
        with self._lock:
            payload = {
                "layers": {layer: {k: list(v) for k, v in bucket.items()} for layer, bucket in self._layers.items()},
                "metrics": {layer: dict(m) for layer, m in self._metrics.items()},
            }
        try:
            r = store.write(payload)
        except TypeError:
            # Values not JSON-safe: degrade to their repr, flag the loss.
            flat = json.loads(json.dumps(payload, default=lambda o: f"<unserializable:{type(o).__name__}>"))
            payload.update(flat)
            r = store.write(payload)
            if isinstance(r, dict):
                r["lossy"] = True
        return r

    def load(self, path: str | None = None) -> dict:
        """Restore layers + telemetry from the durable mirror (P1.1).

        Expired entries are dropped at restore time and counted. Idempotent:
        loading twice yields the same state.
        """
        from pathlib import Path

        from l3.durable_store import DurableJsonStore

        store = DurableJsonStore(Path(path)) if path else self._default_store()
        try:
            data = store.read()
        except Exception as e:  # noqa: BLE001 — cache restore degrades quietly
            logger.debug("tiered_cache: restore skipped: %s", e)
            return {"success": False, "error": str(e)}
        now = time.time()
        restored = 0
        with self._lock:
            for layer, entries in (data.get("layers") or {}).items():
                layer_u = layer.upper()
                if layer_u not in self._layers:
                    continue
                for key, item in entries.items():
                    try:
                        value, ts = item[0], float(item[1])
                    except (TypeError, ValueError, IndexError):
                        continue
                    if now - ts <= self._ttls[layer_u]:
                        self._layers[layer_u][key] = (value, ts)
                        restored += 1
                    else:
                        self._metrics[layer_u]["expired"] += 1
            for layer, m in (data.get("metrics") or {}).items():
                if layer in self._metrics:
                    for k, v in m.items():
                        if k in self._metrics[layer]:
                            self._metrics[layer][k] = max(self._metrics[layer][k], int(v))
        return {"success": True, "restored": restored}


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
