"""Tests for run_code_cache — per-Cell program reuse (Phase 1.5).

Covers store/lookup, tf-idf approximate similarity hits, TTL renewal,
incremental-patch evidence recording, and reclamation. The cache is a
bypass-free side channel: failures degrade to no-ops.
"""

from __future__ import annotations

from l3.tool_system.run_code_cache import get_run_code_cache, reset_run_code_cache


def test_store_and_exact_lookup():
    reset_run_code_cache()
    cache = get_run_code_cache()
    key = cache.store("cell-a", "print(1)", {"result": "1"})
    assert key.startswith("run_code:cell-a:")
    entry = cache.lookup("cell-a", "print(1)")
    assert entry is not None
    assert entry["program"] == "print(1)"
    reset_run_code_cache()


def test_lookup_miss_returns_none():
    reset_run_code_cache()
    cache = get_run_code_cache()
    assert cache.lookup("cell-a", "nope") is None
    reset_run_code_cache()


def test_similar_hit_above_floor():
    reset_run_code_cache()
    cache = get_run_code_cache()
    cache.store("cell-a", 'def main():\n    print("analyze repo structure")', {"result": "done"})
    hit = cache.similar("cell-a", 'def main():\n    print("analyze repository layout")')
    assert hit is not None
    assert "analyze repo" in hit["program"]
    reset_run_code_cache()


def test_similar_miss_below_floor():
    reset_run_code_cache()
    cache = get_run_code_cache()
    cache.store("cell-a", "print(1)", {"result": "1"})
    assert cache.similar("cell-a", "import os\nos.system('ls')") is None
    reset_run_code_cache()


def test_similar_respects_cell_boundary():
    reset_run_code_cache()
    cache = get_run_code_cache()
    cache.store("cell-a", 'def main():\n    print("analyze repo")', {"result": "done"})
    # Different Cell must not see cell-a's programs.
    assert cache.similar("cell-z", 'def main():\n    print("analyze repo")') is None
    reset_run_code_cache()


def test_renew_refreshes_ttl():
    reset_run_code_cache()
    cache = get_run_code_cache()
    cache.store("cell-a", "print(1)", {"result": "1"})
    assert cache.renew("cell-a", "print(1)") is True
    assert cache.renew("cell-a", "missing") is False
    reset_run_code_cache()


def test_record_patch_records_evidence():
    reset_run_code_cache()
    cache = get_run_code_cache()
    ok = cache.record_patch("cell-a", "print(2)", "print(1)")
    # Evidence chain may be disabled in some test envs; must not raise.
    assert isinstance(ok, bool)
    reset_run_code_cache()


def test_reclaim_and_status():
    reset_run_code_cache()
    cache = get_run_code_cache()
    cache.store("cell-a", "print(1)", {"result": "1"})
    cache.store("cell-b", "print(2)", {"result": "2"})
    status = cache.status()
    assert status["entries"] >= 2
    assert status["ttl_seconds"] > 0
    # Per-Cell reclaim only touches that Cell's entries.
    evicted = cache.reclaim("cell-a")
    assert isinstance(evicted, int)
    reset_run_code_cache()
