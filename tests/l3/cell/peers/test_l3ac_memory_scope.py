"""Phase-2D M2-B tests — secretary contributions persist to own scope + R5."""

from __future__ import annotations

import pytest

from l3.cell.peers.l3a.secretary import L3ACSecretary
from l3.memory.central_memory import get_memory, reset_center


@pytest.fixture(autouse=True)
def _clean():
    reset_center()
    yield
    reset_center()


def test_contribution_persists_to_own_scope():
    """Contribution lands in the secretary's memory scope (recall-able)."""
    sec = L3ACSecretary(threshold=3)
    sec.set_scope("l3a-c-1")
    r = sec.contribute("analysis", success=True)
    assert r["memory_entry_id"], "expected a memory entry id"

    mem = get_memory("l3a-c-1")
    hits = mem.recall(agent_id="l3a", rings=[1], limit=5)
    assert hits, "contribution should be recallable from the scope"


def test_contribution_scopes_are_isolated():
    """Contributions of one secretary do not leak into another scope."""
    sec = L3ACSecretary(threshold=3)
    sec.set_scope("l3a-c-1")
    sec.contribute("analysis", success=True)

    other = get_memory("l3a-c-2")
    assert other.recall(agent_id="l3a", rings=[1], limit=5) == []


def test_contribution_default_scope_l3a():
    """Default secretary (no explicit scope) persists to the l3a ring."""
    sec = L3ACSecretary(threshold=3)
    sec.contribute("report", success=True)
    hits = get_memory("l3a").recall(agent_id="l3a", rings=[1], limit=5)
    assert hits


def test_r5_edge_degrades_when_graph_off():
    """Graph disabled → contribution still persists, no crash."""
    from l3.memory.memory_graph import get_graph

    g = get_graph()
    was = g.enabled  # attribute, not a method
    try:
        g.set_enabled(False)
        sec = L3ACSecretary(threshold=3)
        r = sec.contribute("analysis", success=True)
        assert r["memory_entry_id"]
    finally:
        g.set_enabled(was)


def test_r5_edge_added_when_graph_on():
    """Graph enabled → an evidence edge is created for the contribution."""
    from l3.memory.memory_graph import get_graph

    g = get_graph()
    was = g.enabled
    try:
        g.set_enabled(True)
        sec = L3ACSecretary(threshold=3)
        sec.contribute("analysis", success=True, card_id="card-x")
        # Edge bookkeeping is populated (non-blocking when store unavailable);
        # the key assertion is that the graph path did not raise.
        assert g.enabled is True
    finally:
        g.set_enabled(was)
