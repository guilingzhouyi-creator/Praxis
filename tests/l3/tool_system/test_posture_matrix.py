"""B8 tests — posture matrix: config surface + authorization hard bounds."""

from __future__ import annotations

import pytest

from l3.tool_system.posture_matrix import get_posture_matrix, reset_posture_matrix


@pytest.fixture(autouse=True)
def _clean_matrix():
    """Fresh posture matrix per test."""
    reset_posture_matrix()
    yield
    reset_posture_matrix()


def test_defaults_are_productive():
    """Default posture matrix is offensive-off for every domain."""
    pm = get_posture_matrix()
    s = pm.status()
    assert s["api_enabled"] is True
    for _domain, entry in s["domains"].items():
        assert entry["offensive"] is False


def test_enable_offensive_requires_whitelist():
    """Offensive posture without a target whitelist is rejected."""
    pm = get_posture_matrix()
    r = pm.set_domain("attack", offensive=True, target_whitelist=[])
    assert r.get("success") is False
    assert "whitelist" in r.get("error", "")
    assert pm.is_offensive("attack") is False


def test_enable_offensive_with_whitelist_ok():
    """Offensive posture with an explicit whitelist is accepted.

    Whitelist entries are prefix matches (startswith) — a host under the
    allowed prefix passes, an unrelated host is denied.
    """
    pm = get_posture_matrix()
    r = pm.set_domain("attack", offensive=True, target_whitelist=["10.0.0."])
    assert r.get("success") is True
    assert pm.is_offensive("attack") is True
    assert pm.is_offensive() is True  # any-domain offensive
    assert pm.target_allowed("attack", "10.0.0.5") is True
    assert pm.target_allowed("attack", "192.168.1.1") is False


def test_minimal_harness_forbidden_while_offensive():
    """Harness 'minimal' is rejected while any domain is offensive."""
    pm = get_posture_matrix()
    assert pm.validate_harness("minimal")["success"] is True  # productive
    pm.set_domain("attack", offensive=True, target_whitelist=["lab.local"])
    r = pm.validate_harness("minimal")
    assert r.get("success") is False
    assert "forbidden" in r.get("error", "")
    assert pm.validate_harness("governed")["success"] is True


def test_api_switch_gates_writes():
    """Flipping the master switch off blocks subsequent writes."""
    pm = get_posture_matrix()
    pm.set_api_enabled(False)
    r = pm.set_domain("attack", offensive=True, target_whitelist=["lab.local"])
    assert r.get("success") is False
    assert "disabled" in r.get("error", "")


def test_api_handlers_roundtrip():
    """GET/PUT posture handlers expose status and apply a safe enable."""
    from l4.api_handlers.api_handlers_security import (
        posture_api_enabled_set,
        posture_matrix_get,
        posture_matrix_set,
    )

    g = posture_matrix_get({})
    assert g["success"] is True
    assert g["posture"]["api_enabled"] is True

    r = posture_matrix_set({"domain": "attack", "offensive": True, "target_whitelist": ["lab.local"]})
    assert r.get("success") is True

    # Master switch off blocks API writes.
    posture_api_enabled_set({"enabled": False})
    r2 = posture_matrix_set({"domain": "attack", "offensive": False})
    assert r2.get("success") is False
