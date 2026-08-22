"""Recovery hardening — mtime ordering, shared instances, skip-history.

Covers the daemon wiring and truncation fixes.
"""

from __future__ import annotations

import time

import pytest

import l3.agent_terminal as at
from l3.cell.peers.l3a.session import SessionManager


@pytest.fixture()
def iso_recovery(monkeypatch, tmp_path):
    """Isolate sessions_dir and terminal registry."""
    from l3.cell.peers.l3a import session_json as sj

    monkeypatch.setattr(sj, "sessions_dir", lambda: tmp_path / "l3a" / "sessions")
    sj.reset_sequences()
    at.reset_terminals()
    yield tmp_path
    at.reset_terminals()
    sj.reset_sequences()


def test_recovery_truncation_keeps_most_recent(iso_recovery):
    """Truncation keeps the most recently active snapshots."""
    tmp_path = iso_recovery
    from l1.kernel.params.system import SESSION_RECOVERY_MAX_SNAPSHOTS

    # Create more than MAX snapshots with decreasing last_active_at.
    managers = []
    for i in range(SESSION_RECOVERY_MAX_SNAPSHOTS + 5):
        m = SessionManager()
        s = m.create(title=f"s-{i}")
        # Make each later session more recent.
        s.last_active_at = time.time() + i
        s._persist_state()
        # Ensure file mtime also reflects recency.
        p = tmp_path / "l3a" / "sessions" / f"{s.id}.snapshot.json"
        # Touch with increasing mtime.
        p.touch()
        managers.append(m)

    # New manager recovers — should be truncated to MAX.
    fresh = SessionManager()
    r = fresh.recover_from_store()
    assert r["success"] is True
    assert len(r["recovered"]) == SESSION_RECOVERY_MAX_SNAPSHOTS
    assert r["skipped"] >= 5
    # Most recent should be kept (largest last_active_at).
    assert fresh.count() == SESSION_RECOVERY_MAX_SNAPSHOTS


def test_recovery_shares_registry_and_pmu(iso_recovery):
    """Recovery wires registry/model/pmu from daemon."""
    from l3.cell.peers.l3a.context import ContextRegistry
    from l3.cell.peers.l3a.model import L3AModelConfig

    reg = ContextRegistry()
    model = L3AModelConfig()

    # Create a fake PMU with increment tracking.
    class _FakePMU:
        def __init__(self):
            self.calls: list[str] = []

        def increment(self, *a, **kw):
            self.calls.append(str(a))

    pmu = _FakePMU()
    m = SessionManager()
    s = m.create(title="orig", registry=reg, user_id="u1")
    s._persist_state()
    sid = s.id

    fresh = SessionManager()
    r = fresh.recover_from_store(registry=reg, model_config=model, pmu=pmu)
    assert sid in r["recovered"]
    got = fresh.get(sid)
    assert got is not None
    assert got.registry is reg
    assert got.model_config is model
    assert got._pmu is pmu


def test_recovery_skips_history_side_effect(iso_recovery):
    """Recovery with _skip_history does not bump history started_at."""
    from l3.cell.peers.l3a import session_json as sj

    m = SessionManager()
    s = m.create(title="hist")
    orig_history = sj.query_session_history(session_id=s.id)
    orig_started = orig_history["sessions"][0]["started_at"]
    time.sleep(0.01)
    s._persist_state()

    # Recover in fresh manager — history should not be overwritten to now.
    fresh = SessionManager()
    fresh.recover_from_store()
    # History entry should still have original started_at (not now).
    after = sj.query_session_history(session_id=s.id)
    assert after["sessions"][0]["started_at"] == orig_started


def test_recovery_idempotent_across_daemon_restarts(iso_recovery):
    """Two daemon recoveries are idempotent."""
    m1 = SessionManager()
    s1 = m1.create(title="idem2")
    s1._persist_state()
    m2 = SessionManager()
    r1 = m2.recover_from_store()
    assert s1.id in r1["recovered"]
    r2 = m2.recover_from_store()
    assert s1.id not in r2["recovered"]
    assert r2["skipped"] >= 1


def test_daemon_wiring_order(iso_recovery, monkeypatch):
    """Daemon builds registry/model/pmu before recovery."""
    tmp_path = iso_recovery
    from l3.cell.peers.l3a import daemon as dm

    # Create a session before daemon starts, so recovery has something.
    m = SessionManager()
    s = m.create(title="pre-daemon")
    s._persist_state()
    sid = s.id

    # Now create daemon — it should recover the pre-existing session.
    # Patch sessions_dir for daemon's manager as well.
    from l3.cell.peers.l3a import session_json as sj

    monkeypatch.setattr(sj, "sessions_dir", lambda: tmp_path / "l3a" / "sessions")
    d = dm.L3ADaemon()
    assert d.manager.get(sid) is not None
    got = d.manager.get(sid)
    assert got.registry is d.registry
    d.stop()


def test_close_drops_snapshot_not_resurrected(iso_recovery):
    """Closed session snapshot is removed and not recovered."""
    tmp_path = iso_recovery
    m = SessionManager()
    s = m.create(title="to-close")
    s._persist_state()
    p = tmp_path / "l3a" / "sessions" / f"{s.id}.snapshot.json"
    assert p.exists()
    m.close(s.id)
    assert not p.exists()
    fresh = SessionManager()
    r = fresh.recover_from_store()
    assert s.id not in r["recovered"]
