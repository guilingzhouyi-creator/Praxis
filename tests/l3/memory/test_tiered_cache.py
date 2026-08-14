"""2.1-D2 tests — TieredCache three-layer cross-cell cache."""

from __future__ import annotations

import pytest

from l3.memory.tiered_cache import get_tiered_cache, reset_tiered_cache


@pytest.fixture(autouse=True)
def _clean():
    reset_tiered_cache()
    yield
    reset_tiered_cache()


def test_set_get_roundtrip():
    """Values round-trip per layer."""
    tc = get_tiered_cache()
    assert tc.set("L1", "k1", "v1") is True
    assert tc.get("L1", "k1") == "v1"
    assert tc.get("L2", "k1") is None  # layers are isolated


def test_invalid_layer_rejected():
    """Unknown layer names are rejected, not raised."""
    tc = get_tiered_cache()
    assert tc.set("L9", "k", "v") is False
    assert tc.get("L9", "k") is None


def test_expired_entry_returns_none():
    """Expired entries are dropped (returns None, never raises)."""
    tc = get_tiered_cache()
    assert tc.set("L1", "k", "v") is True
    tc._ttls["L1"] = -1.0  # force expiry
    assert tc.get("L1", "k") is None


def test_capacity_eviction_fifo():
    """At capacity, the oldest entry is evicted (FIFO fallback)."""
    tc = get_tiered_cache()
    tc._limits["L2"] = 2
    tc.set("L2", "a", 1)
    tc.set("L2", "b", 2)
    tc.set("L2", "c", 3)  # evicts "a" (oldest)
    assert tc.get("L2", "a") is None
    assert tc.get("L2", "b") == 2
    assert tc.get("L2", "c") == 3


def test_shared_summary_cross_cell():
    """L2 shared summaries are scoped by cell (HTN-B read surface)."""
    tc = get_tiered_cache()
    tc.set_shared_summary("cell-1", "matrix", {"tests": 5})
    assert tc.get_shared_summary("cell-1", "matrix") == {"tests": 5}
    assert tc.get_shared_summary("cell-2", "matrix") is None


def test_archive_index_l3():
    """L3 archive index round-trips meta entries."""
    tc = get_tiered_cache()
    tc.index_archive("diff:src/a.py", {"lines": 10})
    assert tc.get_archive_index("diff:src/a.py") == {"lines": 10}


def test_stats_shape():
    """Stats reports all three layers with entry counts."""
    tc = get_tiered_cache()
    tc.set("L1", "k", "v")
    s = tc.stats()
    assert set(s.keys()) == {"L1", "L2", "L3"}
    assert s["L1"]["entries"] == 1
    assert s["L1"]["capacity"] > 0


def test_invalidate_and_clear():
    """invalidate drops one key; clear drops everything."""
    tc = get_tiered_cache()
    tc.set("L1", "a", 1)
    tc.set("L1", "b", 2)
    assert tc.invalidate("L1", "a") is True
    assert tc.get("L1", "a") is None
    tc.clear()
    assert tc.get("L1", "b") is None
    assert tc.stats()["L1"]["entries"] == 0
