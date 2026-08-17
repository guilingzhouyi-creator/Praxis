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


def test_supply_to_r5_hybrid_uses_engine_and_records_semantic_edge(tmp_path):
    """Hybrid M3 supply feeds a real semantic relation into the R5 graph."""
    from l3.memory.memory_graph import get_graph, reset_graph

    class FakeEngine:
        """Deterministic semantic relation provider for the graph boundary."""

        def generate(self, prompt, max_tokens=0):
            return {"content": "refines"}

    reset_graph()
    graph = get_graph(db_path=str(tmp_path / "supply.db"))
    graph.set_enabled(True)
    assert graph.set_edge_mode("rules")["success"]
    assert graph.set_edge_mode("hybrid")["success"]
    try:
        count = supply_to_r5([_record("r5-a"), _record("r5-b")], engine=FakeEngine())
        assert count == 1
        edges = graph.semantic_edges()
        assert any(edge["relation"] == "refines" for edge in edges)
        assert all(edge["created_by"] == "memory_refinery" for edge in edges)
    finally:
        reset_graph()


def test_supply_to_r5_rules_mode_keeps_rule_edges(tmp_path):
    """Rule topology remains available without invoking an LLM engine."""
    from l3.memory.memory_graph import get_graph, reset_graph

    reset_graph()
    graph = get_graph(db_path=str(tmp_path / "rules.db"))
    graph.set_enabled(True)
    assert graph.set_edge_mode("rules")["success"]
    try:
        records = [_record("rule-a"), _record("rule-b")]
        assert supply_to_r5(records) == 1
        rows = graph._conn.execute(
            "SELECT relation, created_by FROM memory_edges WHERE from_id=? AND to_id=?", ("rule-a", "rule-b")
        ).fetchall()
        assert rows == [("type_chain", "memory_refinery")]
    finally:
        reset_graph()


def test_supply_to_skills_submits_candidate_without_publishing_skill(tmp_path, monkeypatch):
    """Refined records enter the candidate ledger before R4 can publish a skill."""
    import l3.memory.r4_candidate_store as candidates
    from l3.memory.r4_candidate_store import CandidateStore

    monkeypatch.setattr(candidates, "_store", CandidateStore(str(tmp_path / "candidates.json")))

    n = supply_to_skills([_record()])

    assert isinstance(n, int)
    assert n == 1
    candidate = candidates.get_candidate_store().list()[0]
    assert candidate["state"] == "observed"
    assert candidate["skill_name"] == ""


def test_supply_to_skills_uses_registered_candidate_ledger_port():
    """Evidence ingestion uses the typed port, allowing a Rust ledger replacement."""
    from l1.kernel.ports import register_port, reset_ports

    class RecordingLedger:
        """Minimal stand-in for a language-neutral candidate ledger."""

        def __init__(self):
            self.calls: list[tuple[list[dict], str]] = []

        def submit_records(self, records, source="refined_memory", binding=None):
            self.calls.append((records, source))
            return {"success": True, "candidates": [], "submitted": len(records)}

    ledger = RecordingLedger()
    reset_ports()
    register_port("r4_candidates", ledger)
    try:
        assert supply_to_skills([_record()]) == 1
    finally:
        reset_ports()

    assert ledger.calls[0][1] == "refined_memory"


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
