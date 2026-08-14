"""Phase-2C tests — Cell extension registry (C1) + L3A-C secretary wiring (C2)."""

from __future__ import annotations

import pytest

from l3.cell import get_cell, reset_cells
from l3.cell.peers.l3a.secretary import L3ACSecretary, get_secretary, reset_secretary


@pytest.fixture(autouse=True)
def _clean():
    reset_cells()
    reset_secretary()
    yield
    reset_cells()
    reset_secretary()


# ── C1: Cell extension registry ──


def test_register_and_list_extension():
    """register_extension stores a named hook; list returns it."""
    cell = get_cell("cell-1")
    cell.register_extension("department_division", lambda cell_id="", **kw: {"cell_id": cell_id})
    assert "department_division" in cell.list_extensions()


def test_register_extension_idempotent():
    """Registering the same name twice is rejected (idempotent)."""
    cell = get_cell("cell-1")
    fn = lambda cell_id="", **kw: {}  # noqa: E731
    assert cell.register_extension("dept", fn) is True
    assert cell.register_extension("dept", fn) is False


def test_run_extension_invokes_with_cell_id():
    """run_extension passes the cell_id and returns the result."""
    cell = get_cell("cell-1")

    def hook(cell_id: str = "", **kw) -> dict:
        return {"ok": True, "cid": cell_id}

    cell.register_extension("dept", hook)
    r = cell.run_extension("dept")
    assert r["success"] is True
    assert r["result"]["cid"] == "cell-1"


def test_run_extension_missing():
    """Unregistered extension returns a structured error."""
    cell = get_cell("cell-1")
    r = cell.run_extension("ghost")
    assert r["success"] is False
    assert "not registered" in r["error"]


def test_run_extension_tolerates_hook_failure():
    """A raising hook is caught, not propagated."""
    cell = get_cell("cell-1")

    def bad(cell_id: str = "", **kw) -> dict:
        raise RuntimeError("boom")

    cell.register_extension("bad", bad)
    r = cell.run_extension("bad")
    assert r["success"] is False
    assert "boom" in r["error"]


# ── C2: L3A-C secretary wiring ──


def test_secretary_contribute_and_upgrade():
    """Contributions advance the score; crossing the threshold upgrades
    assist -> peer."""
    sec = L3ACSecretary(threshold=3)
    assert sec.mode() == "assist"
    r = sec.contribute("analysis", success=True)
    assert r["mode"] == "assist"
    for _ in range(3):
        sec.contribute("report", success=True)
    assert sec.mode() == "peer"


def test_secretary_singleton_via_get_secretary():
    """get_secretary returns the shared singleton."""
    s1 = get_secretary()
    s2 = get_secretary()
    assert s1 is s2


def test_l3a_daemon_mounts_secretary():
    """L3ADaemon._init_secretary wires the secretary into the lifecycle."""
    from l3.cell.peers.l3a import L3ADaemon

    daemon = L3ADaemon()
    assert daemon._secretary is not None
    assert hasattr(daemon._secretary, "contribute")
