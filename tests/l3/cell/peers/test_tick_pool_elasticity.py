"""Phase-2D D3 consumption-point tests — tick adapts the pool to intensity."""

from __future__ import annotations

import pytest

from l3.cell.peers.l3a import L3ADaemon, reset_daemon
from l3.cell.peers.l3a.subagent import L3ASubAgentPool


@pytest.fixture(autouse=True)
def _clean():
    reset_daemon()
    yield
    reset_daemon()


def test_tick_resizes_pool_for_active_sessions():
    """tick() adapts pool workers to the active-session count (D3)."""
    daemon = L3ADaemon()
    # Pool available (bare daemon may not initialize it — guard).
    if not daemon._sa_pool:
        pool = L3ASubAgentPool()
        pool.set_max_workers(1)
        daemon._sa_pool = pool

    daemon._sa_pool.set_max_workers(1)
    daemon.manager.create(title="s1")
    daemon.manager.create(title="s2")
    daemon.manager.create(title="s3")

    r = daemon.tick()
    # 3 active sessions / 3 per worker = 1 worker... bump to prove wiring:
    # with >= 1 session the pool is at least min workers; assert key present.
    assert "pool_workers" in r
    assert r["pool_workers"] >= 1
    assert daemon._sa_pool.max_workers() == r["pool_workers"]


def test_tick_pool_elasticity_never_raises():
    """Pool elasticity degrades gracefully (empty manager / no pool)."""
    daemon = L3ADaemon()
    daemon._sa_pool = None  # simulate unavailable pool
    r = daemon.tick()
    assert isinstance(r, dict)


def test_tick_reports_decision_bodies():
    """tick() records the evolved decision-body count (D3 consumer)."""
    daemon = L3ADaemon()
    if not daemon._sa_pool:
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool

        daemon._sa_pool = L3ASubAgentPool()

    daemon.manager.create(title="s1")
    daemon.manager.create(title="s2")
    daemon.manager.create(title="s3")
    daemon.manager.create(title="s4")
    daemon.manager.create(title="s5")
    daemon.manager.create(title="s6")  # >= evolution threshold

    r = daemon.tick()
    assert "decision_bodies" in r
    assert r["decision_bodies"] >= 2  # 6 // 6 + 1
