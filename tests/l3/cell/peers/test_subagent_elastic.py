"""Phase-2D D3 tests — elastic subagent pool (task-intensity adaptation)."""

from __future__ import annotations

from l3.cell.peers.l3a.params import SA_MAX_WORKERS_CAP, SA_MAX_WORKERS_MIN
from l3.cell.peers.l3a.subagent import L3ASubAgentPool


def test_default_worker_count():
    """Pool defaults to the params worker count."""
    pool = L3ASubAgentPool()
    assert pool.max_workers() == 4


def test_set_max_workers_resizes():
    """set_max_workers rebuilds the executor at the new size."""
    pool = L3ASubAgentPool()
    r = pool.set_max_workers(8)
    assert r["success"] is True
    assert r["resized"] is True
    assert pool.max_workers() == 8


def test_set_max_workers_noop_same_size():
    """Setting the same size is a no-op (resized=False)."""
    pool = L3ASubAgentPool()
    r = pool.set_max_workers(4)
    assert r["resized"] is False
    assert pool.max_workers() == 4


def test_set_max_workers_bounded_by_caps():
    """Worker count is clamped to the params min/max."""
    pool = L3ASubAgentPool()
    pool.set_max_workers(999)
    assert pool.max_workers() == SA_MAX_WORKERS_CAP
    pool.set_max_workers(0)
    assert pool.max_workers() == SA_MAX_WORKERS_MIN


def test_resize_for_intensity_scales():
    """More active sessions scale the pool up (bounded)."""
    pool = L3ASubAgentPool()
    pool.set_max_workers(SA_MAX_WORKERS_MIN)
    # 30 sessions / 3 per worker = 10 workers (within cap).
    r = pool.resize_for_intensity(30)
    assert r["success"] is True
    assert pool.max_workers() == 10


def test_resize_for_intensity_low_stays_min():
    """Low intensity keeps the pool at the minimum."""
    pool = L3ASubAgentPool()
    pool.resize_for_intensity(1)
    assert pool.max_workers() == SA_MAX_WORKERS_MIN


def test_resize_for_intensity_capped():
    """Very high intensity is capped at the max."""
    pool = L3ASubAgentPool()
    pool.resize_for_intensity(10_000)
    assert pool.max_workers() == SA_MAX_WORKERS_CAP


# ── Decision-body evolution (D3) ──


def test_decision_bodies_min_one():
    """Intensity below the threshold keeps the base secretary (1 body)."""
    from l3.cell.peers.l3a.subagent import decision_bodies_for_intensity

    assert decision_bodies_for_intensity(0) == 1
    assert decision_bodies_for_intensity(1) == 1
    assert decision_bodies_for_intensity(5) == 1


def test_decision_bodies_evolve_with_intensity():
    """Crossing the evolution threshold adds decision bodies."""
    from l3.cell.peers.l3a.subagent import decision_bodies_for_intensity

    assert decision_bodies_for_intensity(6) == 2  # 6 // 6 + 1
    assert decision_bodies_for_intensity(12) == 3  # 12 // 6 + 1
    assert decision_bodies_for_intensity(20) == 4
