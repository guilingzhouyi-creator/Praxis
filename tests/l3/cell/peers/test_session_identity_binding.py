"""Phase-2D B5a tests — session identity binding (create → AgentLoop inheritance)."""

from __future__ import annotations

from l3.cell.peers.l3a.session import Session, SessionManager


def test_session_carries_identity_defaults():
    """Sessions default to the l3a cell/role identity."""
    s = Session(session_id="s1", title="t")
    assert s._cell_id == "l3a"
    assert s._role == "l3a"


def test_session_carries_custom_identity():
    """cell_id/role are settable at construction."""
    s = Session(session_id="s2", title="t", cell_id="l3a", role="l3a-secretary")
    assert s._cell_id == "l3a"
    assert s._role == "l3a-secretary"


def test_session_manager_create_identity_passthrough():
    """SessionManager.create forwards cell_id/role to the Session."""
    mgr = SessionManager()
    s = mgr.create(title="peer", cell_id="l3a", role="l3a-secretary")
    assert s._role == "l3a-secretary"
    assert s._cell_id == "l3a"
    # Defaults preserved.
    d = mgr.create(title="plain")
    assert d._role == "l3a"
    assert d._cell_id == "l3a"


def test_ensure_loop_inherits_session_role():
    """The session's AgentLoop inherits role from the session identity."""
    mgr = SessionManager()
    s = mgr.create(title="peer", role="l3a-secretary", memory_scope="l3a-c-1")
    s._ensure_loop()
    assert s._loop is not None
    assert s._loop._role == "l3a-secretary"
    assert s._loop._cell_id == "l3a"
