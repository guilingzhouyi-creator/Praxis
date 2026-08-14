"""Phase-2 L3A-C tests — secretary runtime toggles (API/configured, not code-embedded)."""

from __future__ import annotations

import pytest

from l3.cell.peers.l3a.secretary import L3ACSecretary, get_secretary, reset_secretary


@pytest.fixture(autouse=True)
def _clean():
    reset_secretary()
    yield
    reset_secretary()


# ── set_enabled ──


def test_set_enabled_override_wins_over_settings():
    """An API-set enable override beats the settings default."""
    sec = L3ACSecretary(threshold=3)
    assert sec.set_enabled(False)["enabled"] is False
    assert sec.enabled() is False

    sec.set_enabled(True)
    assert sec.enabled() is True


def test_set_enabled_none_clears_override():
    """None clears the override back to the settings default."""
    sec = L3ACSecretary(threshold=3)
    sec.set_enabled(False)
    assert sec.enabled() is False
    r = sec.set_enabled(None)
    assert r["enabled"] is True  # settings default is on


# ── set_threshold ──


def test_set_threshold_adjusts_upgrade_point():
    """Lowering the threshold lets contributions upgrade sooner."""
    sec = L3ACSecretary(threshold=10)
    assert sec.mode() == "assist"
    sec.set_threshold(1)
    sec.contribute("analysis", success=True)
    assert sec.mode() == "peer"


def test_set_threshold_rejects_negative():
    """Negative thresholds are rejected."""
    sec = L3ACSecretary()
    r = sec.set_threshold(-1)
    assert r["success"] is False


# ── set_mode (explicit pin, not score-driven) ──


def test_set_mode_pins_peer_before_threshold():
    """An operator can pin peer mode before the score threshold."""
    sec = L3ACSecretary(threshold=100)
    assert sec.mode() == "assist"
    r = sec.set_mode("peer")
    assert r["success"] is True
    assert sec.mode() == "peer"


def test_set_mode_auto_restores_score_driven():
    """auto unpins and returns to the score-driven transition."""
    sec = L3ACSecretary(threshold=2)
    sec.set_mode("peer")
    assert sec.mode() == "peer"
    sec.set_mode("auto")
    assert sec.mode() == "assist"  # score 0 < threshold 2


def test_set_mode_invalid_rejected():
    """Invalid modes are rejected."""
    sec = L3ACSecretary()
    r = sec.set_mode("supervisor")
    assert r["success"] is False


# ── API surface ──


def test_secretary_update_api_enabled_and_threshold():
    """PUT /api/v2/l3a/secretary toggles enabled/threshold/mode."""
    from l4.api_handlers.api_handlers_security import secretary_update

    r = secretary_update({"enabled": False, "threshold": 5, "mode": "peer"})
    assert r["success"] is True
    sec = get_secretary()
    assert sec.enabled() is False
    assert sec.mode() == "peer"

    r2 = secretary_update({"enabled": None, "mode": "auto"})
    assert r2["success"] is True
    assert get_secretary().enabled() is True
    assert get_secretary().mode() == "assist"


def test_secretary_update_api_invalid_mode():
    """Invalid mode through the API returns a structured error."""
    from l4.api_handlers.api_handlers_security import secretary_update

    r = secretary_update({"mode": "boss"})
    assert r["success"] is False
    assert "invalid mode" in r["error"]


def test_mixin_delegate_resolves():
    """The ApiHandlers mixin exposes _secretary_update."""
    from l4.api_handlers import ApiHandlers

    h = ApiHandlers()
    assert callable(getattr(h, "_secretary_update", None))
