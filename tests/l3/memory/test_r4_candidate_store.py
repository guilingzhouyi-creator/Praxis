"""Tests for the evidence-backed R4 skill candidate ledger."""

from __future__ import annotations

from l3.memory.r4_candidate_store import CandidateStore


def _record(entry_id: str, content: str = "insight", **extra):
    return {
        "entry_id": entry_id,
        "entry_type": "note",
        "cell_id": "cell-build",
        "agent_id": "agent-builder",
        "role": "builder",
        "content": content,
        **extra,
    }


def test_submission_accumulates_evidence_without_publishing_skill(tmp_path):
    """Refined records create an observed candidate, not a registered skill."""
    store = CandidateStore(str(tmp_path / "candidates.json"))

    result = store.submit_records([_record("memory-1")])

    assert result["success"] is True
    candidate = result["candidates"][0]
    assert candidate["state"] == "observed"
    assert candidate["skill_name"] == ""
    assert candidate["binding"]["cell_ids"] == ["cell-build"]
    assert candidate["binding"]["roles"] == ["builder"]
    assert candidate["binding"]["agent_ids"] == ["agent-builder"]
    assert candidate["binding"]["postures"] == ["productive"]


def test_matching_records_deduplicate_and_pass_validation_threshold(tmp_path):
    """Same-scope evidence aggregates before a candidate becomes validated."""
    store = CandidateStore(str(tmp_path / "candidates.json"))

    first = store.submit_records([_record("memory-1", "first insight")])["candidates"][0]
    second = store.submit_records([_record("memory-2", "second insight")])["candidates"][0]

    assert first["id"] == second["id"]
    assert len(second["evidence"]) == 2
    validation = store.validate(second["id"])
    assert validation["success"] is True
    assert validation["candidate"]["state"] == "validated"


def test_candidate_lifecycle_requires_validation_and_canary(tmp_path):
    """Publication cannot skip evidence validation or the canary phase."""
    store = CandidateStore(str(tmp_path / "candidates.json"))
    candidate = store.submit_records([_record("memory-1")])["candidates"][0]

    assert store.transition(candidate["id"], "canary", skill_name="candidate-skill")["success"] is False
    store.submit_records([_record("memory-2")])
    assert store.validate(candidate["id"])["success"] is True
    assert store.transition(candidate["id"], "active", skill_name="candidate-skill")["success"] is False
    canary = store.transition(candidate["id"], "canary", skill_name="candidate-skill")
    assert canary["success"] is True
    assert store.transition(candidate["id"], "active")["candidate"]["state"] == "active"


def test_candidate_ledger_restores_from_persistent_state(tmp_path):
    """Candidate evidence and lifecycle state survive a store restart."""
    path = tmp_path / "candidates.json"
    first = CandidateStore(str(path))
    candidate = first.submit_records([_record("memory-1")])["candidates"][0]

    restored = CandidateStore(str(path)).get(candidate["id"])

    assert restored is not None
    assert restored["evidence"][0]["entry_id"] == "memory-1"


def test_validated_candidate_publishes_as_canary_then_activates(tmp_path, monkeypatch):
    """Publication produces a scoped canary that activation can promote."""
    import l3.memory.r4_agent as r4_agent
    from l1.kernel.skill import get_skill_manager, reset_skill_manager
    from l3.memory.r4_candidate_store import activate_candidate, publish_candidate

    class _FakeR4:
        def evolve_skill(self, **kwargs):
            get_skill_manager().create(
                "published-candidate-skill",
                prompt="Bound candidate skill.",
                tags=["evolved", "card:build"],
                binding=kwargs["binding"],
                status=kwargs["status"],
                internal=True,
            )
            return {"success": True, "skill": "published-candidate-skill"}

    reset_skill_manager()
    monkeypatch.setattr(r4_agent, "get_r4_agent", lambda: _FakeR4())
    try:
        store = CandidateStore(str(tmp_path / "candidates.json"))
        candidate = store.submit_records([_record("memory-1"), _record("memory-2")])["candidates"][0]
        import l3.memory.r4_candidate_store as candidates

        monkeypatch.setattr(candidates, "_store", store)
        published = publish_candidate(candidate["id"], "Create a build skill from validated evidence.")

        assert published["success"] is True
        assert published["candidate"]["state"] == "canary"
        assert get_skill_manager().get("published-candidate-skill")["status"] == "canary"
        assert activate_candidate(candidate["id"])["candidate"]["state"] == "active"
        assert get_skill_manager().get("published-candidate-skill")["status"] == "active"
    finally:
        reset_skill_manager()


def test_tool_failure_trace_enters_candidate_ledger(tmp_path, monkeypatch):
    """R4 failure tracking contributes scoped evidence without publishing a skill."""
    from types import SimpleNamespace

    import l1.kernel.paths as paths
    import l3.memory.r4_candidate_store as candidates
    from l3.memory.r4_agent import R4Agent
    from l3.memory.r4_candidate_store import CandidateStore

    monkeypatch.setattr(paths, "get_paths", lambda: SimpleNamespace(skill_lean_dir=str(tmp_path / "lean")))
    store = CandidateStore(str(tmp_path / "candidates.json"))
    monkeypatch.setattr(candidates, "_store", store)

    R4Agent().track_tool_failure(
        agent_id="agent-builder",
        tool_name="run_tests",
        args={},
        error="test failed",
        turn_log=[],
        domain="build",
        nature="build",
    )

    candidate = store.list()[0]
    assert candidate["evidence"][0]["source"] == "tool_failure"
    assert candidate["binding"]["agent_ids"] == ["agent-builder"]
    assert candidate["binding"]["card_natures"] == ["build"]
