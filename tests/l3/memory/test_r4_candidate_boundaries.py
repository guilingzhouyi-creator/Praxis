"""Regression tests for R4 candidate lifecycle boundaries and supply input."""

from __future__ import annotations

from l3.memory.r4_candidate_store import CandidateStore


def _record(entry_id: str, **extra: object) -> dict:
    """Build a minimally scoped evidence record for a candidate."""
    return {
        "entry_id": entry_id,
        "entry_type": "note",
        "cell_id": "cell-build",
        "agent_id": "agent-builder",
        "role": "builder",
        "content": f"evidence {entry_id}",
        **extra,
    }


def test_binding_without_agent_dimension_matches_agent_context():
    """Cell/role/card bindings remain eligible when an agent id is supplied."""
    from l1.kernel.skill import get_skill_manager, reset_skill_manager
    from l3.memory.r4_agent import R4Agent

    reset_skill_manager()
    try:
        result = get_skill_manager().create(
            "bound-candidate",
            description="Use when reviewing build changes.",
            prompt="Review the build diff before publishing.",
            tags=["evolved", "card:build"],
            status="canary",
            binding={
                "cell_ids": ["cell-build"],
                "roles": ["builder"],
                "card_natures": ["build"],
                "postures": ["productive"],
            },
            internal=True,
        )
        assert result["success"] is True

        matching = R4Agent().get_evolved_skills(
            agent_id="agent-without-a-binding",
            cell_id="cell-build",
            role="builder",
            tags=["card:build"],
        )
        assert "bound-candidate" in {skill["name"] for skill in matching}

        wrong_cell = R4Agent().get_evolved_skills(
            agent_id="agent-without-a-binding",
            cell_id="cell-other",
            role="builder",
            tags=["card:build"],
        )
        assert "bound-candidate" not in {skill["name"] for skill in wrong_cell}
    finally:
        reset_skill_manager()


def test_candidate_lifecycle_rejects_backward_and_terminal_transitions(tmp_path):
    """A candidate can only move forward and retired candidates stay terminal."""
    store = CandidateStore(str(tmp_path / "candidates.json"))
    candidate = store.submit_records([_record("memory-1"), _record("memory-2")])["candidates"][0]
    candidate_id = candidate["id"]

    assert store.validate(candidate_id)["success"] is True
    assert store.transition(candidate_id, "canary", skill_name="candidate-skill")["success"] is True
    assert store.transition(candidate_id, "validated")["success"] is False
    assert store.transition(candidate_id, "observed")["success"] is False
    assert store.transition(candidate_id, "active")["success"] is True
    assert store.transition(candidate_id, "canary")["success"] is False
    assert store.transition(candidate_id, "retired")["success"] is True
    assert store.transition(candidate_id, "active")["success"] is False


def test_thought_supply_preserves_reasoning_content(tmp_path, monkeypatch):
    """Thought JSON is converted to the lesson field without replacing its text."""
    from l3.cell.peers.l3a.session_json import append_thought, reset_sequences
    from l3.memory.r4_skill_supply import load_thought_lessons, reset_supply_cache

    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path))
    reset_sequences()
    reset_supply_cache()
    try:
        append_thought("supply-regression", turn=1, input_seq=1, reasoning_text="step through the diff")
        append_thought("supply-regression", turn=2, input_seq=2, reasoning_text="verify the changed contract")

        lessons = [lesson for lesson in load_thought_lessons() if "[session:supply-regression]" in lesson["prompt"]]

        assert [lesson["knowledge"]["lesson"] for lesson in lessons] == [
            "step through the diff",
            "verify the changed contract",
        ]
    finally:
        reset_supply_cache()
        reset_sequences()
