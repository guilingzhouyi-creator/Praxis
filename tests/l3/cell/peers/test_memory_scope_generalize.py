"""Phase-2D B1 tests — memory scope generalization (get_memory(scope))."""

from __future__ import annotations

import pytest

from l3.cell.peers.l3a.session import Session, SessionManager
from l3.memory.central_memory import get_l3a_memory, get_memory, reset_center


@pytest.fixture(autouse=True)
def _clean():
    reset_center()
    yield
    reset_center()


def test_get_memory_arbitrary_scope_isolated():
    """Each scope gets an isolated memory instance (persisted separately)."""
    m1 = get_memory("l3a-c-1")
    m2 = get_memory("l3a-c-2")
    assert m1 is not m2


def test_get_memory_same_scope_is_singleton():
    """The same scope resolves to the same instance."""
    assert get_memory("l3a-c-1") is get_memory("l3a-c-1")


def test_get_l3a_memory_is_scope_l3a():
    """get_l3a_memory() is just get_memory("l3a") — backward compatible."""
    assert get_l3a_memory() is get_memory("l3a")


def test_session_carries_memory_scope():
    """Session stores its memory_scope (default l3a)."""
    s = Session(session_id="s1", title="t")
    assert s.memory_scope == "l3a"
    s2 = Session(session_id="s2", title="t", memory_scope="l3a-c-9")
    assert s2.memory_scope == "l3a-c-9"


def test_session_manager_create_passthrough():
    """SessionManager.create forwards memory_scope to the Session."""
    mgr = SessionManager()
    s = mgr.create(title="peer", memory_scope="l3a-c-2")
    assert s.memory_scope == "l3a-c-2"
    assert s.id.startswith("l3a-")

    default = mgr.create(title="default")
    assert default.memory_scope == "l3a"
