"""run_code program cache — per-Cell reuse of model-written tool programs.

Phase 1.5 of the Code Mode / PTC capability: a model-written ``run_code``
program is stored in the per-Cell tiered-cache layer with a TTL. When a new
program is submitted, the tf-idf retriever scores it against the Cell's
cached programs; a hit above the similarity floor lets the caller reuse the
cached entry (supply only an incremental patch) instead of re-entering the
full program, and its TTL is renewed. Expired entries are reclaimed
automatically on access. The cache is a bypass-free side channel: it never
mutates the pipeline or audit chain, and degrades to no-ops on error.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Any

from l1.kernel.params.system import HASH_TRUNC_LONG, LOG_TRUNC_2000
from l1.kernel.params.tool import (
    CODE_RUN_CACHE_KEY_PREFIX,
    CODE_RUN_CACHE_LAYER,
    CODE_RUN_CACHE_MAX_ENTRIES,
    CODE_RUN_CACHE_TTL,
    CODE_RUN_SIMILARITY_MIN_SCORE,
)
from l3.memory.skill_retriever import TfIdfSkillRetriever

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {"enabled": True}
_lock = threading.RLock()
_retriever = TfIdfSkillRetriever()


def _cache_key(cell_id: str, program: str) -> str:
    """Deterministic cache key for a program in a Cell."""
    digest = hashlib.sha256(program.encode("utf-8")).hexdigest()[:HASH_TRUNC_LONG]
    return f"{CODE_RUN_CACHE_KEY_PREFIX}{cell_id}:{digest}"


class RunCodeProgramCache:
    """Per-Cell program cache backed by the tiered-cache L1 layer."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def store(self, cell_id: str, program: str, meta: dict | None = None) -> str:
        """Store a program in the Cell's cache layer; returns its key."""
        try:
            from l3.memory.tiered_cache import get_tiered_cache

            key = _cache_key(cell_id, program)
            entry = {
                "program": program,
                "cell_id": cell_id,
                "language": (meta or {}).get("language", "python"),
                "result": (meta or {}).get("result", ""),
                "created": (meta or {}).get("created", ""),
            }
            get_tiered_cache().set(CODE_RUN_CACHE_LAYER, key, entry)
            return key
        except Exception as e:
            logger.debug("run_code_cache: store failed: %s", e)
            return ""

    def lookup(self, cell_id: str, program: str) -> dict | None:
        """Return the exact cached entry for a program, or None."""
        try:
            from l3.memory.tiered_cache import get_tiered_cache

            key = _cache_key(cell_id, program)
            return get_tiered_cache().get(CODE_RUN_CACHE_LAYER, key)
        except Exception as e:
            logger.debug("run_code_cache: lookup failed: %s", e)
            return None

    def similar(self, cell_id: str, program: str) -> dict | None:
        """Return the most similar cached program above the floor, or None.

        Uses tf-idf cosine similarity (zero new dependencies); a hit renews
        the matched entry's TTL by re-storing it.
        """
        try:
            from l3.memory.tiered_cache import get_tiered_cache

            # Search only this Cell's entries by prefix scan.
            candidates: list[dict] = []
            bucket = get_tiered_cache()._layers.get(CODE_RUN_CACHE_LAYER, {})  # type: ignore[attr-defined]
            prefix = f"{CODE_RUN_CACHE_KEY_PREFIX}{cell_id}:"
            for key, (value, _ts) in list(bucket.items()):
                if key.startswith(prefix) and isinstance(value, dict):
                    candidates.append({"name": key, "description": "", "prompt": value.get("program", "")})
            if not candidates:
                return None
            ranked = _retriever.rank(program, candidates, limit=1, min_score=CODE_RUN_SIMILARITY_MIN_SCORE)
            if not ranked:
                return None
            hit = ranked[0]
            entry = get_tiered_cache().get(CODE_RUN_CACHE_LAYER, hit["name"])
            if entry:
                # TTL renewal: re-store to refresh the timestamp.
                get_tiered_cache().set(CODE_RUN_CACHE_LAYER, hit["name"], entry)
            return entry
        except Exception as e:
            logger.debug("run_code_cache: similar failed: %s", e)
            return None

    def renew(self, cell_id: str, program: str) -> bool:
        """Renew the TTL of a cached program (approximate-hit path)."""
        try:
            from l3.memory.tiered_cache import get_tiered_cache

            key = _cache_key(cell_id, program)
            entry = get_tiered_cache().get(CODE_RUN_CACHE_LAYER, key)
            if entry is None:
                return False
            get_tiered_cache().set(CODE_RUN_CACHE_LAYER, key, entry)
            return True
        except Exception as e:
            logger.debug("run_code_cache: renew failed: %s", e)
            return False

    def record_patch(self, cell_id: str, program: str, cached_program: str) -> bool:
        """Record the incremental patch (cached vs submitted) as evidence.

        The unified diff between the cached program and the new submission is
        recorded on the security-evidence chain (``phase="run_code_cache"``)
        so program reuse leaves an auditable trace. Degrades to a no-op on
        error — the cache is a bypass-free side channel.

        Args:
            cell_id: Cell owning the cache area.
            program: newly submitted program.
            cached_program: matched cached program.

        Returns:
            True when the patch was recorded, False otherwise.
        """
        try:
            import difflib

            diff = "".join(
                difflib.unified_diff(
                    cached_program.splitlines(keepends=True),
                    program.splitlines(keepends=True),
                    fromfile="cached.py",
                    tofile="submitted.py",
                )
            )
            from l3.tool_system.security_evidence import DECISION_CHANGE, record_evidence

            record_evidence(
                phase="run_code_cache",
                gate="incremental_patch",
                decision=DECISION_CHANGE,
                target=f"cell:{cell_id}",
                source="run_code",
                tags={"diff_chars": str(len(diff))},
                detail=diff[:LOG_TRUNC_2000],
                chain_kind="ambient",
            )
            return True
        except Exception as e:
            logger.debug("run_code_cache: record_patch failed: %s", e)
            return False

    def reclaim(self, cell_id: str = "") -> int:
        """Evict expired entries (per-Cell or global); returns evicted count.

        The tiered-cache ``get`` path already drops expired entries lazily;
        this is an explicit sweep used at Cell teardown or on demand.
        """
        try:
            from l3.memory.tiered_cache import get_tiered_cache

            bucket = get_tiered_cache()._layers.get(CODE_RUN_CACHE_LAYER, {})  # type: ignore[attr-defined]
            now = _now()
            evicted = 0
            prefix = f"{CODE_RUN_CACHE_KEY_PREFIX}{cell_id}:" if cell_id else CODE_RUN_CACHE_KEY_PREFIX
            for key, (_value, ts) in list(bucket.items()):
                if key.startswith(prefix) and now - ts > CODE_RUN_CACHE_TTL:
                    bucket.pop(key, None)
                    evicted += 1
            return evicted
        except Exception as e:
            logger.debug("run_code_cache: reclaim failed: %s", e)
            return 0

    def status(self) -> dict:
        """Return cache stats for observability."""
        try:
            from l3.memory.tiered_cache import get_tiered_cache

            bucket = get_tiered_cache()._layers.get(CODE_RUN_CACHE_LAYER, {})  # type: ignore[attr-defined]
            return {
                "enabled": _state["enabled"],
                "entries": len(bucket),
                "max_entries": CODE_RUN_CACHE_MAX_ENTRIES,
                "ttl_seconds": CODE_RUN_CACHE_TTL,
                "similarity_floor": CODE_RUN_SIMILARITY_MIN_SCORE,
            }
        except Exception:
            return {"enabled": _state["enabled"], "entries": 0}


def _now() -> float:
    """Time source (separate for test override)."""
    import time

    return time.time()


_cache: RunCodeProgramCache | None = None
_cache_lock = threading.RLock()


def get_run_code_cache() -> RunCodeProgramCache:
    """Get the run_code program cache singleton."""
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = RunCodeProgramCache()
        return _cache


def reset_run_code_cache() -> None:
    """Reset the run_code program cache singleton (tests / lifecycle)."""
    global _cache
    with _cache_lock:
        _cache = None
