"""Phase-3 M3 tests — memory supply chain (R5 / re-inject / skills / Agent.md)."""

from __future__ import annotations

import pytest

from l3.memory.memory_domain_filter import get_memory_filter, reset_memory_filter
from l3.memory.memory_supply_chain import agent_md_active, re_inject_filtered, supply_to_r5, supply_to_skills


@pytest.fixture(autouse=True)
def _clean():
    reset_memory_filter()
    yield
    reset_memory_filter()


def _record(entry_id: str = "e1", entry_type: str = "note", score: float = 4.0):
    return {
        "entry_id": entry_id,
        "entry_type": entry_type,
        "refinery_score": score,
        "agent_id": "a1",
        "content": "insight " * 20,
    }


def test_re_inject_passes_through_when_disabled():
    """Filter disabled → re-injection is unchanged (backward compatible)."""
    entries = [{"tags": ["build"], "cell_id": "c1"}, {"tags": ["test"], "cell_id": "c2"}]
    assert re_inject_filtered(entries, cell_id="c1") == entries


def test_re_inject_filters_domain_when_enabled():
    """Filter enabled → foreign-domain entries are dropped on re-inject."""
    get_memory_filter().set_switches(enabled=True)
    entries = [{"tags": [], "cell_id": "c1"}, {"tags": [], "cell_id": "c2"}]
    kept = re_inject_filtered(entries, cell_id="c1")
    assert len(kept) == 1
    assert kept[0]["cell_id"] == "c1"


def test_supply_to_r5_returns_count():
    """R5 supply returns an edge count (0 when graph disabled — no raise)."""
    n = supply_to_r5([_record()])
    assert isinstance(n, int)
    assert n >= 0


def test_supply_to_skills_degrades():
    """Skill supply never raises (returns a count, possibly 0)."""
    n = supply_to_skills([_record()])
    assert isinstance(n, int)


def test_agent_md_active_threshold():
    """Per-Cell Agent.md activates at the department threshold (2+ Cells)."""
    assert agent_md_active(cell_count=1) is False
    assert agent_md_active(cell_count=2) is True
    assert agent_md_active(cell_count=5) is True


def test_supply_after_refine_orchestrates():
    """supply_after_refine feeds R5 + skills + agent_md (degrades, never raises)."""
    from l3.memory.memory_supply_chain import supply_after_refine

    out = supply_after_refine([_record()])
    assert "r5_edges" in out
    assert "skills_supplied" in out
    assert "agent_md_active" in out
    assert isinstance(out["r5_edges"], int)
    assert isinstance(out["skills_supplied"], int)
