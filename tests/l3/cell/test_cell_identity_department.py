"""Phase-2B tests — Cell-level identity + configurable department types.

Covers:
  B1  Cell identity is distinct from Agent identities (params surface)
  B2  department config load (departments.yaml), type validation, routing
      by dept_type (testing is one case, not hardcoded)
  B3  L3A-assisted department suggestion from user intent
"""

from __future__ import annotations

import pytest

from l1.kernel.params.agent import (
    CELL_IDENTITY_DEFAULT,
    CELL_IDENTITY_TEST,
    CELL_IDENTITY_VALID,
    DEPARTMENT_TYPES,
    IDENTITY_FIELDS,
)
from l3.cell.department import get_department_manager, reset_department_manager, suggest_department


@pytest.fixture(autouse=True)
def _clean():
    reset_department_manager()
    yield
    reset_department_manager()


# ── B1: Cell identity distinct from Agent identities ──


def test_cell_identity_distinct_from_agent_identity():
    """Cell identity surface is separate from Agent build/test/review."""
    assert CELL_IDENTITY_VALID == ("general", "test", "review")
    # The three Agent identity fields are NOT Cell identities.
    assert IDENTITY_FIELDS == ("build", "test", "review")
    assert "build" not in CELL_IDENTITY_VALID
    assert CELL_IDENTITY_DEFAULT == "general"
    assert CELL_IDENTITY_TEST == "test"


# ── B2: configurable department types ──


def test_department_yaml_loads_test_department():
    """config/discovery/departments.yaml defines the testing department."""
    from pathlib import Path

    p = Path("config/discovery/departments.yaml")
    assert p.exists()
    mgr = get_department_manager()
    status = mgr.status()
    assert "test" in status["departments"]


def test_department_types_are_configurable():
    """DEPARTMENT_TYPES includes general/build/test/review/custom — testing
    is one configurable case, not a hardcoded department."""
    assert "general" in DEPARTMENT_TYPES
    assert "test" in DEPARTMENT_TYPES
    assert "review" in DEPARTMENT_TYPES
    assert "custom" in DEPARTMENT_TYPES


def test_route_content_matches_dept_type_when_active():
    """When division is active, test content routes by dept_type."""
    from l1.kernel.settings import get_settings

    get_settings().set("departments.enabled", True)
    mgr = get_department_manager()
    r = mgr.route_content("test", cell_count=2)
    assert r.get("routed") is True
    assert r.get("department") == "test"
    assert r.get("dept_type") == "test"
    assert r.get("cell_identity") == "test"


def test_route_content_inactive_stays_generic():
    """Without activation, content stays in the generic pool."""
    mgr = get_department_manager()
    r = mgr.route_content("test", cell_count=2)
    assert r.get("routed") is False
    assert r.get("department") == ""


# ── B3: L3A-assisted department suggestion ──


def test_suggest_department_build():
    assert suggest_department("implement the login feature") == "build"


def test_suggest_department_test():
    assert suggest_department("run the test suite", domain="test") == "test"


def test_suggest_department_review():
    assert suggest_department("review the pull request") == "review"


def test_suggest_department_fallback():
    assert suggest_department("hello world greeting") == "general"
