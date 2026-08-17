"""GateChain G2 — verified identity required at/above the identity ring (W2.4)."""

from __future__ import annotations

import pytest

from l1.kernel.gatechain import get_gatechain
from l1.kernel.params.gatechain import GATECHAIN_REQUIRE_IDENTITY_RING


@pytest.fixture(autouse=True)
def _fresh_whitelist() -> None:
    """Give G1 a known tool so the chain reaches G2."""
    gc = get_gatechain()
    gc._known_tools = frozenset(["read_file"])
    yield
    gc._known_tools = frozenset()


def _g2_step(ring: int, verified: bool) -> dict:
    """Run the chain for a spawned agent and return its G2 step."""
    from l1.kernel.process import get_table

    name = f"agent-r{ring}-{'v' if verified else 'u'}"
    pt = get_table()
    pt.spawn(name, role="test", ring=ring)
    if verified:
        pt.mark_identity_verified(name)
    r = get_gatechain().check("read_file", name)
    return next(s for s in r["steps"] if s["gate"] == "G2")


def test_unverified_below_threshold_warns() -> None:
    """Ring-1 unverified agents keep the legacy WARN."""
    assert _g2_step(1, False)["result"] == "WARN"


def test_unverified_at_threshold_blocks() -> None:
    """Ring >= threshold without a verified identity is BLOCKed."""
    step = _g2_step(GATECHAIN_REQUIRE_IDENTITY_RING, False)
    assert step["result"] == "BLOCK"
    assert "fail-closed" in step.get("reason", "")


def test_verified_high_ring_passes() -> None:
    """Verified high-ring agents pass G2."""
    assert _g2_step(GATECHAIN_REQUIRE_IDENTITY_RING, True)["result"] == "PASS"
