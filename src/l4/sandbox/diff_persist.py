"""Diff persistence (2.1-D5) — ring buffer + periodic flush + R4 eviction.

Frontend-heavy mode only: stitched diff concatenations are kept in a ring
buffer and written to disk periodically (NOT per second). When the ring
fills, the oldest stitched diff is not deleted — it is compressed to a
binary stream (zlib) and evicted into the R4 archive (fonds="diff"), with
an eviction event reported to the L3A bus / user.

The whole store is gated by the ``diff.persist.enabled`` switch (default
off): TUI / terminal runs never enable it, so the cost of the cache
architecture is paid only by the heavy frontend.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

from l1.kernel.params.system import (
    DIFF_PERSIST_ENABLED_DEFAULT,
    DIFF_PERSIST_FILE,
    DIFF_PERSIST_FLUSH_INTERVAL,
    DIFF_PERSIST_R4_FONDS,
    DIFF_PERSIST_R4_SERIES,
    DIFF_PERSIST_RING_CAPACITY,
)

logger = logging.getLogger(__name__)

_persist_lock = threading.RLock()
_persist: DiffPersistStore | None = None


class DiffPersistStore:
    """Ring-buffer stitched-diff store with periodic flush and R4 eviction."""

    def __init__(self, persist_path: str = "") -> None:
        self._lock = threading.RLock()
        self._enabled = DIFF_PERSIST_ENABLED_DEFAULT
        self._ring: list[dict] = []  # stitched diff records (oldest first)
        self._capacity = DIFF_PERSIST_RING_CAPACITY
        self._flush_interval = DIFF_PERSIST_FLUSH_INTERVAL
        self._last_flush = 0.0
        self._evicted = 0
        self._persisted = 0  # records appended to the durable JSONL store
        self._persist_path = persist_path or self._default_persist_path()

    @staticmethod
    def _default_persist_path() -> str:
        """Resolve the durable JSONL path from PraxisPaths (data_dir)."""
        try:
            from l1.kernel.paths import get_paths

            return get_paths().diff_persist_file
        except Exception as e:
            logger.debug("diff_persist: path resolve skipped: %s", e)
            return DIFF_PERSIST_FILE

    def set_persist_path(self, path: str) -> None:
        """Override the durable store path (used by tests)."""
        with self._lock:
            self._persist_path = path

    # ── Switch (frontend-heavy only) ──

    def set_enabled(self, enabled: bool) -> dict:
        """Enable/disable the persist store (API-controlled)."""
        with self._lock:
            self._enabled = bool(enabled)
            if not self._enabled:
                self._ring.clear()
        return {"success": True, "enabled": self._enabled}

    def enabled(self) -> bool:
        return self._enabled

    # ── Append / flush ──

    def append(self, diff_id: str, stitched: str, meta: dict | None = None, hunks: list[dict] | None = None) -> dict:
        """Stitch a diff into the ring buffer; evict oldest when full.

        Args:
            diff_id: Stable diff identifier.
            stitched: Human-readable unified-diff text (frontend display).
            meta: Optional structured metadata (path, agent, tool, ...).
            hunks: Optional structured hunks (compute_hunks output) — the
                structure-aware representation stored for the codec and for
                header fast-path reads at eviction time.
        """
        if not self._enabled:
            return {"success": False, "error": "diff persist disabled (frontend-heavy only)"}
        with self._lock:
            record: dict = {
                "diff_id": diff_id,
                "stitched": stitched,
                "meta": dict(meta or {}),
                "ts": time.time(),
            }
            if hunks:
                record["hunks"] = hunks
            self._ring.append(record)
            evicted = 0
            while len(self._ring) > self._capacity:
                self._evict_one()
                evicted += 1
            # Periodic flush (never per-second).
            now = time.time()
            if now - self._last_flush >= self._flush_interval:
                self._flush()
        return {"success": True, "ring": len(self._ring), "evicted": evicted}

    def _evict_one(self) -> None:
        """Compress the oldest diff record to a binary stream → R4 archive.

        Uses the structure-aware codec: when the record carries structured
        hunks it is encoded as a hunk frame (enum dictionary coding + row
        deltas + 8-byte plaintext header for threshold fast-path reads);
        otherwise it falls back to the text-envelope codec. Versioned and
        backward compatible with legacy plain-zlib records.
        """
        if not self._ring:
            return
        record = self._ring.pop(0)
        self._evicted += 1
        try:
            from l4.sandbox.diff_codec import FRAME_REVIEW, compress_record, encode_hunks
            from l4.sandbox.diff_dict import get_dictionary

            hunks = record.get("hunks")
            if hunks:
                # L2 review frame: structure-aware, zstd-dict when the shared
                # dictionary is available (Phase 2), zlib otherwise.
                binary = encode_hunks(hunks, frame_type=FRAME_REVIEW, dictionary=get_dictionary())
            else:
                binary = compress_record(record)
            self._archive_to_r4(record, binary)
            # Report eviction to the L3A bus / user.
            from l1.kernel.event import get_bus

            get_bus().emit_event(
                "diff_evicted_to_r4",
                {"diff_id": record["diff_id"], "bytes": len(binary), "reason": "ring overflow"},
                source="diff_persist",
            )
        except Exception as e:
            logger.warning("diff_persist: eviction failed: %s", e)

    def _archive_to_r4(self, record: dict, binary: bytes) -> None:
        """Store the compressed stream into the R4 archive (best-effort).

        L3 archive tier (Phase 2): the frame is re-compressed with zstd
        level 19 (``PDZ19`` prefix) for maximal ratio before the opaque
        latin-1 storage; degrades to the raw frame when zstandard is
        unavailable. Decoders check the prefix to unwrap.
        """
        try:
            from l3.tools._archive import archive_store

            archive_store(
                {
                    "fonds": DIFF_PERSIST_R4_FONDS,
                    "series": DIFF_PERSIST_R4_SERIES,
                    "content": self._archive_compress(binary).decode("latin-1"),  # opaque binary → R4 content
                    "tags": f"diff_id={record['diff_id']}",
                },
                agent_id="diff_persist",
            )
        except Exception as e:
            logger.debug("diff_persist: R4 archive skipped: %s", e)

    @staticmethod
    def _archive_compress(binary: bytes) -> bytes:
        """Zstd-19 archive compression (L3 tier); raw fallback when unavailable."""
        try:
            import zstandard

            cctx = zstandard.ZstdCompressor(level=19)
            return b"PDZ19" + cctx.compress(binary)
        except Exception as e:
            logger.debug("diff_persist: archive zstd skipped: %s", e)
            return binary

    def _flush(self) -> None:
        """Periodic durable write: append unflushed stitched diffs to JSONL.

        Append-only JSONL (crash-recoverable): every stitched diff is written
        once at the fixed flush interval; ``recover()`` replays the file back
        into the ring after a crash. Writes are best-effort — a failing disk
        never breaks the append path.
        """
        try:
            path = self._persist_path
            if not path:
                return
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with self._lock:
                pending = self._ring[self._persisted :]
                if not pending:
                    self._last_flush = time.time()
                    return
                lines = [json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in pending]
                with open(path, "a", encoding="utf-8") as f:
                    f.writelines(lines)
                self._persisted = len(self._ring)
            self._last_flush = time.time()
        except Exception as e:
            logger.warning("diff_persist: flush failed: %s", e)

    def recover(self) -> int:
        """Replay the durable JSONL store back into the ring (crash recovery).

        Reads the append-only file and restores every stitched diff record
        (oldest first, respecting the ring capacity). Records already evicted
        to R4 are re-archived on the next overflow — nothing is lost.

        Returns:
            Number of records recovered (0 when the file is absent/empty).
        """
        try:
            path = self._persist_path
            if not path or not os.path.exists(path):
                return 0
            recovered = 0
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    self._ring.append(record)
                    recovered += 1
                    if len(self._ring) > self._capacity:
                        self._evict_one()
            with self._lock:
                self._persisted = len(self._ring)
            if recovered:
                logger.info("diff_persist: recovered %d stitched diffs from %s", recovered, path)
            return recovered
        except Exception as e:
            logger.debug("diff_persist: recover failed: %s", e)
            return 0

    def list_stitched(self, limit: int = 50) -> list[dict]:
        """Return recent stitched diffs for frontend consumption.

        Frontend-heavy surface: the caller (browser / dashboard) reads the
        ring buffer through the API — each record exposes diff_id, path,
        meta and the stitched text for display.
        """
        with self._lock:
            records = list(self._ring[-limit:]) if limit > 0 else list(self._ring)
        return [
            {
                "diff_id": r.get("diff_id", ""),
                "path": (r.get("meta") or {}).get("path", ""),
                "meta": r.get("meta", {}),
                "ts": r.get("ts", 0.0),
                "stitched": r.get("stitched", ""),
            }
            for r in records
        ]

    def stats(self) -> dict:
        """Store statistics for the status surface."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "ring": len(self._ring),
                "capacity": self._capacity,
                "evicted_to_r4": self._evicted,
                "persisted": self._persisted,
                "flush_interval": self._flush_interval,
                "persist_path": self._persist_path,
            }


def get_diff_persist() -> DiffPersistStore:
    """Get the global DiffPersistStore singleton."""
    global _persist
    with _persist_lock:
        if _persist is None:
            _persist = DiffPersistStore()
        return _persist


def reset_diff_persist() -> None:
    """Reset the singleton (used by tests)."""
    global _persist
    with _persist_lock:
        _persist = None
