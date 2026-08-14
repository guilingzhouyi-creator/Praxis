"""B7 tests — cross-chain evidence aggregation (security_evidence)."""

from __future__ import annotations

import pytest

from l3.tool_system.security_evidence import SecurityEvidence, reset_evidence


@pytest.fixture(autouse=True)
def _clean_evidence(tmp_path):
    """Isolated evidence store per test."""
    reset_evidence()
    ev = SecurityEvidence(path=str(tmp_path / "evidence.jsonl"))
    yield ev
    reset_evidence()


def _seed_chains(ev: SecurityEvidence) -> None:
    """Create two chains with distinct verdicts for aggregation."""
    from l3.tool_system.security_evidence import DECISION_ALLOW, DECISION_FULL_POWER

    cid_a = ev.begin_chain("probe", source="tool-x", meta={})
    ev.record(phase="g2", gate="approval", decision=DECISION_ALLOW, target="read_file", chain_kind="probe")
    ev.close_chain(cid_a, reason="done")  # verdict: clean

    cid_b = ev.begin_chain("attack", source="tool-y", meta={})
    ev.record(phase="g4", gate="chain", decision=DECISION_FULL_POWER, target="write_file", chain_kind="attack")
    ev.record(phase="use_skill", gate="skill", decision=DECISION_ALLOW, target="offensive_skill", chain_kind="attack")
    ev.close_chain(cid_b, reason="done")  # verdict: warranted


def test_cross_chain_analyze_all(tmp_path):
    """Aggregation over all chains reports verdicts and decision counts."""
    ev = SecurityEvidence(path=str(tmp_path / "evidence.jsonl"))
    _seed_chains(ev)
    r = ev.cross_chain_analyze()
    assert r["success"] is True
    assert r["chains"] == 2
    assert r["verdicts"].get("clean", 0) == 1
    assert r["verdicts"].get("warranted", 0) == 1
    assert r["decisions"].get("FULL_POWER", 0) == 1
    assert "read_file" in r["skills"]


def test_cross_chain_analyze_filtered_by_kind(tmp_path):
    """Filtering by kind limits the aggregation to matching chains."""
    ev = SecurityEvidence(path=str(tmp_path / "evidence.jsonl"))
    _seed_chains(ev)
    r = ev.cross_chain_analyze(kind="attack")
    assert r["kind"] == "attack"
    assert r["chains"] == 1
    assert r["verdicts"].get("warranted", 0) == 1
    assert "clean" not in r["verdicts"]


def test_cross_chain_analyze_empty(_clean_evidence):
    """No chains → empty aggregation without raising.

    Uses the fixture's isolated evidence store (tmp file) — the global
    get_evidence() singleton may carry chains from other tests.
    """
    ev = _clean_evidence
    r = ev.cross_chain_analyze()
    assert r["success"] is True
    assert r["chains"] == 0
    assert r["verdicts"] == {}


def test_api_handler_cross_analyze(_clean_evidence, monkeypatch):
    """GET /api/v2/security/evidence/analyze surfaces the aggregation.

    Uses the fixture's isolated store (tmp file) and points the singleton
    get_evidence at it — the global default-path singleton may carry chains
    from other tests.
    """
    from l3.tool_system import security_evidence as _se
    from l4.api_handlers.api_handlers_security import security_evidence_cross_analyze

    ev = _clean_evidence
    monkeypatch.setattr(_se, "get_evidence", lambda: ev)
    _seed_chains(ev)
    r = security_evidence_cross_analyze({"kind": ""})
    assert r["success"] is True
    assert r["chains"] == 2
