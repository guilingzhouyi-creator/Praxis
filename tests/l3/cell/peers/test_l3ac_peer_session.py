"""Phase-2D D1/M1-B tests — secretary upgrade spawns a scope-bound background session."""

from __future__ import annotations

import pytest

from l3.cell.peers.l3a.secretary import L3ACSecretary, reset_secretary


@pytest.fixture(autouse=True)
def _clean():
    reset_secretary()
    yield
    reset_secretary()


def test_upgrade_spawns_peer_session():
    """Crossing the threshold spawns the secretary's background session."""
    sec = L3ACSecretary(threshold=2)
    sec.set_scope("l3a-c-1")
    r1 = sec.contribute("analysis", success=True)
    assert r1["upgraded"] is False
    assert r1["peer_session_id"] == ""

    r2 = sec.contribute("report", success=True)
    assert r2["upgraded"] is True
    assert r2["peer_session_id"].startswith("l3a-")
    assert sec.peer_session_id() == r2["peer_session_id"]


def test_peer_session_is_scope_bound():
    """The spawned session carries the secretary's memory scope + identity."""
    sec = L3ACSecretary(threshold=1)
    sec.set_scope("l3a-c-2")
    sid = sec.contribute("card", success=True)["peer_session_id"]
    assert sid

    from l3.cell.peers.l3a import get_daemon

    s = get_daemon().manager.get(sid)
    assert s is not None
    assert s.memory_scope == "l3a-c-2"
    assert s._role == "l3a-secretary"


def test_upgrade_spawn_idempotent():
    """Only the first upgrade spawns; later upgrades reuse the session."""
    sec = L3ACSecretary(threshold=1)
    first = sec.contribute("a", success=True)["peer_session_id"]
    sec.contribute("b", success=True)
    assert sec.peer_session_id() == first


def test_scope_default_and_set():
    """Scope defaults to l3a and is settable (extension-first)."""
    sec = L3ACSecretary()
    assert sec.scope() == "l3a"
    assert sec.set_scope("l3a-c-9")["scope"] == "l3a-c-9"
    assert sec.set_scope("")["scope"] == "l3a"
