"""Phase-2D B5b/B5c/B5d tests — secretary identity set + memory<->identity + card linkage."""

from __future__ import annotations

import pytest

from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager
from l3.cell.peers.l3a.secretary import L3ACSecretary
from l3.memory.central_memory import reset_center


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    # Isolate the identity-binding persistence file per test.
    monkeypatch.setenv("PRAXIS_IDENTITY_STATE", str(tmp_path / "id_bindings.json"))
    reset_identity_binding_manager()
    reset_center()
    yield
    reset_identity_binding_manager()
    reset_center()


# ── B5b: secretary identity set ──


def test_secretary_identity_set_default():
    """Unbound secretary resolves the full default identity set."""
    mgr = get_identity_binding_manager()
    assert mgr.identity_set_for("l3a", "l3a-secretary") == ("build", "test", "review")


def test_secretary_identity_set_narrowed_by_binding():
    """A binding's domain_tags narrow the secretary identity set."""
    mgr = get_identity_binding_manager()
    mgr.bind("l3a", "l3a-secretary", "You are the testing secretary.", domain_tags=["test"], internal=True)
    assert mgr.identity_set_for("l3a", "l3a-secretary") == ("test",)


# ── B5c: memory <-> identity linkage ──


def test_contribution_memory_entries_carry_identity_tags():
    """Contribution memory entries carry the secretary's identity tags."""
    mgr = get_identity_binding_manager()
    mgr.bind("l3a", "l3a-secretary", "Testing secretary.", domain_tags=["test"], internal=True)

    sec = L3ACSecretary(threshold=3)
    r = sec.contribute("analysis", success=True)
    assert r["memory_entry_id"]

    from l3.memory.central_memory import get_memory

    hits = get_memory("l3a").recall(agent_id="l3a", rings=[1], limit=5)
    assert hits
    assert "test" in (hits[0].tags if hasattr(hits[0], "tags") else [])


# ── B5d: card-domain linkage reuse ──


def test_resolve_domain_fragment_hits_secretary_binding():
    """Card-domain expert fragment resolves for the secretary binding."""
    mgr = get_identity_binding_manager()
    mgr.bind("l3a", "l3a-secretary", "You are the domain testing expert.", domain_tags=["test"], internal=True)

    frag = mgr.resolve_domain_fragment("l3a", "test")
    assert frag == "You are the domain testing expert."


def test_resolve_domain_fragment_miss_empty():
    """Unmatched card domain degrades to '' (no expert)."""
    mgr = get_identity_binding_manager()
    assert mgr.resolve_domain_fragment("l3a", "codegen") == ""
