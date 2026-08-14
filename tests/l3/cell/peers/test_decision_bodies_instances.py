"""Phase-3 D3-completion tests — decision bodies materialize as secretary instances."""

from __future__ import annotations

import pytest

from l3.cell.peers.l3a import L3ADaemon, reset_daemon
from l3.cell.peers.l3a.secretary import (
    get_or_create_secretary,
    get_secretary,
    list_secretaries,
    reset_secretary,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_daemon()
    reset_secretary()
    yield
    reset_daemon()
    reset_secretary()


def test_evolved_secretary_isolated_scope():
    """Evolved secretaries are distinct instances bound to their scope."""
    s1 = get_or_create_secretary("l3a-c-1")
    s2 = get_or_create_secretary("l3a-c-2")
    assert s1 is not s2
    assert s1.scope() == "l3a-c-1"
    assert s2.scope() == "l3a-c-2"


def test_l3a_scope_maps_to_singleton():
    """The l3a scope resolves to the canonical singleton (backward compat)."""
    assert get_or_create_secretary("l3a") is get_secretary()


def test_same_scope_is_singleton():
    """Repeated requests for a scope return the same instance."""
    assert get_or_create_secretary("l3a-c-9") is get_or_create_secretary("l3a-c-9")


def test_list_secretaries():
    """list_secretaries reports evolved instances (scope/mode/score)."""
    get_or_create_secretary("l3a-c-1")
    get_or_create_secretary("l3a-c-2")
    names = [s["scope"] for s in list_secretaries()]
    assert "l3a-c-1" in names
    assert "l3a-c-2" in names


def test_tick_materializes_decision_bodies():
    """tick() creates secretary instances matching the evolved body count."""
    daemon = L3ADaemon()
    if not daemon._sa_pool:
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool

        daemon._sa_pool = L3ASubAgentPool()

    for i in range(6):
        daemon.manager.create(title=f"s{i}")  # intensity >= evolution threshold

    r = daemon.tick()
    assert r["decision_bodies"] >= 2
    assert len(r["secretary_scopes"]) == r["decision_bodies"] - 1
    # Evolved instances are materialized in the registry.
    assert "l3a-c-1" in [s["scope"] for s in list_secretaries()]
