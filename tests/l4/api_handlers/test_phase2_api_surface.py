"""Phase-2 API surface tests — identity/set, departments, L3A-C secretary.

Verifies the new API handlers are wired and behave (the audit found the
Phase-2A/B/C features had no API exposure before this pass).
"""

from __future__ import annotations

import pytest

from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager
from l3.cell.peers.l3a.secretary import reset_secretary


@pytest.fixture(autouse=True)
def _clean():
    reset_identity_binding_manager()
    reset_secretary()
    yield
    reset_identity_binding_manager()
    reset_secretary()


def test_identity_set_handler():
    """GET /api/v2/identity/set resolves the generic identity set."""
    from l4.api_handlers.api_handlers_identity import handle_identity_set_get

    r = handle_identity_set_get({"cell_id": "cell-1", "role": "writer"})
    assert r["success"] is True
    assert r["identity_set"] == ["build", "test", "review"]

    # Narrowed by binding domain_tags.
    mgr = get_identity_binding_manager()
    mgr.bind("cell-1", "tester", "test identity", domain_tags=["test"], internal=True)
    r2 = handle_identity_set_get({"cell_id": "cell-1", "role": "tester"})
    assert r2["identity_set"] == ["test"]

    # Missing fields → structured error.
    r3 = handle_identity_set_get({})
    assert r3["success"] is False


def test_departments_status_handler():
    """GET /api/v2/departments surfaces division status."""
    from l4.api_handlers.api_handlers_security import departments_status

    r = departments_status({})
    assert r["success"] is True
    assert "departments" in r
    assert "test" in r["departments"]


def test_departments_suggest_handler():
    """POST /api/v2/departments/suggest returns a department suggestion."""
    from l4.api_handlers.api_handlers_security import departments_suggest

    r = departments_suggest({"intent": "run the test suite", "domain": "test"})
    assert r["success"] is True
    assert r["suggestion"] == "test"

    r2 = departments_suggest({"intent": "hello world"})
    assert r2["suggestion"] == "general"

    r3 = departments_suggest({})
    assert r3["success"] is False


def test_secretary_status_and_contribute_handlers():
    """GET/POST /api/v2/l3a/secretary expose status + contributions."""
    from l4.api_handlers.api_handlers_security import secretary_contribute, secretary_status

    s = secretary_status({})
    assert s["success"] is True
    assert s["mode"] == "assist"

    c = secretary_contribute({"kind": "analysis", "success": True})
    assert c["recorded"] is True
    assert c["score"] == 1

    e = secretary_contribute({})
    assert e["success"] is False


def test_mixin_delegates_resolve():
    """The ApiHandlers mixin methods route to the module handlers."""
    from l4.api_handlers import ApiHandlers

    h = ApiHandlers()
    assert callable(getattr(h, "_departments_status", None))
    assert callable(getattr(h, "_departments_suggest", None))
    assert callable(getattr(h, "_secretary_status", None))
    assert callable(getattr(h, "_secretary_contribute", None))
    assert callable(getattr(h, "_posture_matrix_get", None))
    assert callable(getattr(h, "_security_evidence_cross_analyze", None))
