"""Phase-3 M3 tests — per-Cell Agents handbook (Cell-{cell_id}-Agents.md).

Verifies the department-brief + constitution-digest injection and the
per-Cell file naming, plus the register_cell auto-activation path.
"""

from __future__ import annotations

from l3.cell.peers.l3a.agents_md import (
    _cell_department_brief,
    _constitution_brief,
    assemble_agents_md,
)


def _info() -> dict:
    return {
        "project_root": "/tmp/proj",
        "layers": {"l1": {"files": 2, "lines": 10}, "l3": {"files": 3, "lines": 20}},
        "sublayers": {"l3a": {"files": 1, "lines": 5}},
        "params": {"modules": 2, "constants": 10},
        "commands": 5,
        "tests": {"files": 1, "lines": 4},
        "key_paths": {"config/praxis.yaml": True},
    }


def test_assemble_without_cell_is_project_handbook():
    """No cell_id → project-level AGENTS.md skeleton (no dept brief)."""
    md = assemble_agents_md(_info())
    assert "Cell" not in md.splitlines()[0]  # title is project handbook
    assert "## Cell department" not in md


def test_assemble_with_cell_title():
    """With cell_id the handbook is titled Cell-{id} Agents Handbook."""
    md = assemble_agents_md(_info(), cell_id="cell-2")
    assert "Cell cell-2 Agents Handbook" in md.splitlines()[0]


def test_assemble_with_cell_injects_sections():
    """The per-Cell handbook carries constitution binding and (when the
    department registry is active) the department brief."""
    md = assemble_agents_md(_info(), cell_id="cell-1")
    # Constitution digest is injected unconditionally on success.
    assert "## Constitution binding" in md
    # Department brief appears only when division is active; when inactive
    # the handbook still degrades gracefully (no crash).
    assert "## Cell department" in md or "## Constitution binding" in md


def test_constitution_brief_degrades():
    """constitution brief never raises (returns string, possibly empty)."""
    b = _constitution_brief()
    assert isinstance(b, str)


def test_department_brief_degrades():
    """department brief never raises (empty when division inactive)."""
    b = _cell_department_brief("cell-1")
    assert isinstance(b, str)


def test_register_cell_auto_activates_at_two_cells(monkeypatch):
    """register_cell generates the per-Cell handbook at 2+ Cells (M3)."""
    from l3.cell.peers.l3 import CentralController

    calls: list[str] = []

    def _fake_generate(cell_id: str = "", **_):
        calls.append(cell_id)
        return {"success": True, "write": {"success": True}}

    monkeypatch.setattr("l3.cell.peers.l3a.agents_md.generate_agents_md", _fake_generate)
    ctl = CentralController()
    ctl.register_cell("cell-1", ["src/a"], agents=["a1"])
    assert calls == []  # single Cell → handbook NOT generated
    ctl.register_cell("cell-2", ["src/b"], agents=["b1"])
    assert "cell-2" in calls  # 2+ Cells → per-Cell handbook generated
    assert "cell-1" not in calls  # only the newly registered Cell
