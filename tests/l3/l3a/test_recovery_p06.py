"""P0.6 slice tests — persistence joined to recovery (idempotent graph rebuild)."""

from __future__ import annotations

import json

import pytest

import l3.agent_terminal as at
from l3.agent_terminal import get_session
from l3.cell.peers.l3a.session import SessionManager


@pytest.fixture()
def iso(monkeypatch, tmp_path):
    """Isolate the per-session storage dir; clean terminal registry around."""
    from l3.cell.peers.l3a import session_json as sj

    monkeypatch.setattr(sj, "sessions_dir", lambda: tmp_path / "l3a" / "sessions")
    sj.reset_sequences()
    at.reset_terminals()
    yield tmp_path
    at.reset_terminals()
    sj.reset_sequences()


def test_persist_then_recover_roundtrip(iso):
    """Recovery rebuilds the SAME identity/scope/counters from the store."""
    a = SessionManager()
    s = a.create(
        title="probe",
        user_id="u-42",
        memory_scope="l3a-c-9",
        cell_id="cell-7",
        role="peer",
    )
    s.turn_count = 5
    s.card_count = 2
    s._persist_state()

    b = SessionManager()
    r = b.recover_from_store()
    assert r["success"] is True
    assert s.id in r["recovered"]

    got = b.get(s.id)
    assert got is not None
    info = got.info()
    assert info["title"] == "probe"
    assert info["turn_count"] == 5
    assert info["card_count"] == 2
    # P0.2 identity fields survived the round trip
    rec = get_session(s.id)
    assert rec["meta"]["user_id"] == "u-42"
    assert rec["meta"]["memory_scope"] == "l3a-c-9"
    assert rec["meta"]["cell_id"] == "cell-7"
    assert rec["meta"]["role"] == "peer"


def test_recovery_is_idempotent(iso):
    """Running recovery twice changes nothing the second time."""
    a = SessionManager()
    s = a.create(title="idem")
    s._persist_state()

    b = SessionManager()
    r1 = b.recover_from_store()
    assert s.id in r1["recovered"]
    r2 = b.recover_from_store()
    assert s.id not in r2["recovered"]
    assert r2["skipped"] >= 1
    assert b.count() == 1


def test_closed_session_not_recovered(iso):
    """Close drops the live snapshot — closed sessions stay archived-only."""
    a = SessionManager()
    s = a.create(title="ephemera")
    s._persist_state()
    snap_path = iso / "l3a" / "sessions" / f"{s.id}.snapshot.json"
    assert snap_path.exists()

    a.close(s.id)
    assert not snap_path.exists()

    b = SessionManager()
    r = b.recover_from_store()
    assert r["recovered"] == []


def test_multi_session_independent_recovery(iso):
    """Two persisted sessions recover independently addressable."""
    a = SessionManager()
    s1 = a.create(title="one", user_id="u1", memory_scope="l3a")
    s2 = a.create(title="two", user_id="u2", memory_scope="l3a-c-1")
    s1._persist_state()
    s2._persist_state()

    b = SessionManager()
    r = b.recover_from_store()
    assert set(r["recovered"]) == {s1.id, s2.id}
    g1, g2 = b.get(s1.id), b.get(s2.id)
    assert g1 is not None and g2 is not None
    assert g1.user_id == "u1" and g2.user_id == "u2"
    # terminal bindings: both bound on the shared L3A terminal, none lost
    from l3.agent_terminal import list_sessions

    rows = {row["session_id"]: row for row in list_sessions()["sessions"]}
    assert rows[s1.id]["state"] == "active"
    assert rows[s2.id]["state"] == "active"


def test_snapshot_store_keys_by_session(iso):
    """The old single-AGENT_ID clobber is gone: snapshots are per-session files."""
    from pathlib import Path

    from l3.cell.peers.l3a import session_json as sj

    a = SessionManager()
    s1 = a.create(title="k1")
    s2 = a.create(title="k2")
    s1._persist_state()
    s2._persist_state()
    d = Path(str(sj.sessions_dir()))
    assert (d / f"{s1.id}.snapshot.json").exists()
    assert (d / f"{s2.id}.snapshot.json").exists()
    env1 = json.loads((d / f"{s1.id}.snapshot.json").read_text(encoding="utf-8"))
    assert env1["payload"]["session_id"] == s1.id
