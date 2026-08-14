"""Phase-2 gap-fill tests — card-domain linkage ([3]) + L3A decision center ([13][16])."""

from __future__ import annotations

import pytest

from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    from l1.kernel import prompts as _prompts

    # Isolate the identity-binding persistence file per test so a prior
    # test's bindings never leak into this one via _restore().
    monkeypatch.setenv("PRAXIS_IDENTITY_STATE", str(tmp_path / "id_bindings.json"))
    reset_identity_binding_manager()
    _saved = dict(_prompts._overrides)
    yield
    reset_identity_binding_manager()
    _prompts._overrides.clear()
    _prompts._overrides.update(_saved)


# ── [3] card-domain linkage: resolve_domain_fragment ──


def test_resolve_domain_fragment_hits_binding():
    """A card domain matching a binding's domain_tags returns its fragment."""
    mgr = get_identity_binding_manager()
    mgr.bind("cell-1", "tester", "You are the testing expert.", domain_tags=["test"], internal=True)
    frag = mgr.resolve_domain_fragment("cell-1", "test")
    assert frag == "You are the testing expert."


def test_resolve_domain_fragment_miss_returns_empty():
    """Unmatched domain → "" (no expert known, graceful)."""
    mgr = get_identity_binding_manager()
    mgr.bind("cell-1", "tester", "You are the testing expert.", domain_tags=["test"], internal=True)
    assert mgr.resolve_domain_fragment("cell-1", "codegen") == ""
    assert mgr.resolve_domain_fragment("cell-1", "") == ""


def test_resolve_domain_fragment_empty_bindings():
    """No bindings in the cell → "" without raising."""
    mgr = get_identity_binding_manager()
    assert mgr.resolve_domain_fragment("cell-9", "test") == ""


# ── [13][16] L3A decision center ──


def test_l3a_decide_suggests_test_department():
    """decide() interprets a test intent and suggests the test department."""
    from l3.cell.peers.l3a import L3ADaemon

    daemon = L3ADaemon()
    r = daemon.decide("run the test suite", domain="test")
    assert r["success"] is True
    assert r["identity"] == "test"
    assert r["department_suggestion"] == "test"


def test_l3a_decide_build_intent():
    """A build intent maps to the build identity/department suggestion."""
    from l3.cell.peers.l3a import L3ADaemon

    daemon = L3ADaemon()
    r = daemon.decide("implement the login feature")
    assert r["identity"] == "build"
    assert r["department_suggestion"] == "build"


def test_l3a_decide_unmatched_intent():
    """Unmatched intents degrade to the general suggestion, not an error."""
    from l3.cell.peers.l3a import L3ADaemon

    daemon = L3ADaemon()
    r = daemon.decide("hello world greeting")
    assert r["success"] is True
    assert r["identity"] == ""
    assert r["department_suggestion"] == "general"
