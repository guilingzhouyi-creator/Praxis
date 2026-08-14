"""Phase-2D end-to-end smoke test — the whole chain must run without raising.

Single-path smoke: secretary contributions → threshold upgrade → scope-bound
peer session → contribution memory (own scope) → decision-layer role →
delegate → tick elasticity (pool + decision bodies). This validates that
the modules WIRE together, complementing the per-unit tests.
"""

from __future__ import annotations

import pytest

from l3.cell.peers.l3a import reset_daemon
from l3.cell.peers.l3a.secretary import L3ACSecretary, reset_secretary
from l3.memory.central_memory import reset_center


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_IDENTITY_STATE", str(tmp_path / "id_bindings.json"))
    reset_daemon()
    reset_secretary()
    reset_center()
    yield
    reset_daemon()
    reset_secretary()
    reset_center()


def test_phase2d_end_to_end_smoke():
    """Secretary upgrade → scope session → memory → decision → delegate → tick."""
    # Use the daemon SINGLETON: _spawn_peer_session registers the peer
    # session via get_daemon().manager — a fresh L3ADaemon() instance has
    # a different manager and would miss it.
    from l3.cell.peers.l3a import get_daemon

    daemon = get_daemon()
    sec = L3ACSecretary(threshold=2)
    sec.set_scope("l3a-c-smoke")
    daemon._secretary = sec

    # 1. Contributions → upgrade → scope-bound peer session (D1).
    r1 = sec.contribute("analysis", success=True)
    assert r1["upgraded"] is False
    r2 = sec.contribute("report", success=True, card_id="card-smoke")
    assert r2["upgraded"] is True
    peer_id = r2["peer_session_id"]
    assert peer_id.startswith("l3a-")

    # 2. The peer session is registered with the daemon and scope-bound.
    peer = daemon.manager.get(peer_id)
    assert peer is not None
    assert peer.memory_scope == "l3a-c-smoke"
    assert peer._role == "l3a-secretary"

    # 3. Contribution memory landed in the secretary's OWN scope.
    from l3.memory.central_memory import get_memory

    hits = get_memory("l3a-c-smoke").recall(agent_id="l3a", rings=[1], limit=5)
    assert hits, "contribution memory should be recallable from the scope"

    # 4. Decision-layer role (D2): cells < 2 → first.
    assert daemon.decision_layer(cell_count=1) == "first"
    assert daemon.decision_layer(cell_count=2) == "second"

    # 5. Delegate (D2) returns a structured result (pool may be absent).
    d = daemon.delegate("smoke decision", spec="secretary")
    assert isinstance(d, dict)

    # 6. Tick elasticity (D3): pool workers + decision bodies recorded.
    if not daemon._sa_pool:
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool

        daemon._sa_pool = L3ASubAgentPool()
    daemon.manager.create(title="extra-1")
    tick = daemon.tick()
    assert "pool_workers" in tick
    assert "decision_bodies" in tick
    assert tick["decision_bodies"] >= 1
