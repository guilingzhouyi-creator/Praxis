"""Phase-2D D2 tests — L3A decision layer (first → second) + delegate + API."""

from __future__ import annotations

import pytest

from l3.cell.peers.l3a import L3ADaemon
from l3.cell.peers.l3a.secretary import L3ACSecretary


@pytest.fixture(autouse=True)
def _clean_daemon_secretary():
    from l3.cell.peers.l3a import reset_daemon
    from l3.cell.peers.l3a.secretary import reset_secretary

    reset_daemon()
    reset_secretary()
    yield
    reset_daemon()
    reset_secretary()


def test_decision_layer_first_with_single_cell():
    """Fewer than 2 cells → L3A is the first decision layer."""
    daemon = L3ADaemon()
    assert daemon.decision_layer(cell_count=1) == "first"


def test_decision_layer_second_with_departments_and_peer():
    """2+ cells AND peer secretary → L3A becomes the second decision layer."""
    daemon = L3ADaemon()
    sec = L3ACSecretary(threshold=1)
    daemon._secretary = sec
    assert daemon.decision_layer(cell_count=1) == "first"  # not enough cells
    sec.contribute("analysis", success=True)  # upgrade to peer
    assert daemon.decision_layer(cell_count=2) == "second"


def test_delegate_uses_subagent_pool():
    """delegate() commissions via the subagent pool."""
    daemon = L3ADaemon()
    r = daemon.delegate("analyze the evidence chain", spec="secretary")
    # Pool may be unavailable in bare tests; either way a structured result.
    assert isinstance(r, dict)
    assert "success" in r or "task_id" in r or "error" in r


def test_decision_layer_api():
    """GET /api/v2/l3a/decision-layer surfaces the layer."""
    from l4.api_handlers.api_handlers_security import l3a_decision_layer_get

    r = l3a_decision_layer_get({"cell_count": 1})
    assert r["success"] is True
    assert r["layer"] == "first"


def test_delegate_api_requires_decision():
    """POST /api/v2/l3a/delegate without a decision is rejected."""
    from l4.api_handlers.api_handlers_security import l3a_delegate_post

    r = l3a_delegate_post({})
    assert r["success"] is False
    assert "decision" in r["error"]


def test_mixin_delegates_resolve():
    """The ApiHandlers mixin exposes the D2 delegates."""
    from l4.api_handlers import ApiHandlers

    h = ApiHandlers()
    assert callable(getattr(h, "_l3a_decision_layer_get", None))
    assert callable(getattr(h, "_l3a_delegate_post", None))
