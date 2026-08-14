"""B6 tests — R5 evidence edges: add_evidence_edge + close_chain linkage."""

from __future__ import annotations

from l3.memory.memory_graph import MemoryGraph
from l3.tool_system.security_evidence import SecurityEvidence


def _enabled_graph(tmp_path) -> MemoryGraph:
    """Build an enabled in-memory/temp graph for edge assertions."""
    g = MemoryGraph(db_path=str(tmp_path / "mgraph.db"), enabled=True)
    g._conn.execute("DELETE FROM memory_edges")
    g._conn.commit()
    return g


def test_add_evidence_edge_creates_edge(tmp_path):
    """add_evidence_edge inserts an 'evidence' relation row."""
    g = _enabled_graph(tmp_path)
    r = g.add_evidence_edge("chain-1", "source-1", weight=2.0, created_by="test")
    assert r.get("success") is True
    row = g._conn.execute(
        "SELECT relation, weight FROM memory_edges WHERE from_id=? AND to_id=?",
        ("chain-1", "source-1"),
    ).fetchone()
    assert row is not None
    assert row[0] == "evidence"
    assert row[1] == 2.0


def test_add_evidence_edge_dedup(tmp_path):
    """Duplicate evidence edges are not inserted twice."""
    g = _enabled_graph(tmp_path)
    g.add_evidence_edge("chain-1", "source-1")
    r = g.add_evidence_edge("chain-1", "source-1")
    assert r.get("duplicate") is True
    count = g._conn.execute(
        "SELECT COUNT(*) FROM memory_edges WHERE from_id='chain-1' AND to_id='source-1'"
    ).fetchone()[0]
    assert count == 1


def test_add_evidence_edge_graceful_when_disabled(tmp_path):
    """Disabled graph returns a structured failure without raising."""
    g = MemoryGraph(db_path=str(tmp_path / "disabled.db"), enabled=False)
    r = g.add_evidence_edge("chain-1", "source-1")
    assert r.get("success") is False
    assert "disabled" in r.get("note", "")


def test_close_chain_linkage_does_not_raise(tmp_path):
    """close_chain tolerates a disabled memory graph (non-blocking)."""
    ev = SecurityEvidence(path=str(tmp_path / "evidence.jsonl"))
    cid = ev.begin_chain("probe", source="test-tool", meta={})
    ev.record(
        phase="probe",
        source="test-tool",
        target="probe_target",
        tags={"kind": "probe"},
    )
    # MemoryGraph defaults to disabled — linkage must degrade gracefully.
    r = ev.close_chain(cid, reason="done")
    assert r.get("success") is True
