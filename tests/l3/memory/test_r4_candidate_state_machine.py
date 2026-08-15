"""Regression tests for R4 candidate lifecycle and explicit skill bindings."""

from __future__ import annotations

import threading


def _record(entry_id: str) -> dict:
    """Build scoped evidence sufficient to exercise candidate transitions."""
    return {
        "entry_id": entry_id,
        "entry_type": "note",
        "cell_id": "cell-build",
        "agent_id": "agent-builder",
        "role": "builder",
        "content": f"evidence {entry_id}",
    }


def test_candidate_lifecycle_rejects_state_rollback_and_reuse(tmp_path):
    """Lifecycle transitions are forward-only, with retirement as the terminal state."""
    from l3.memory.r4_candidate_store import CandidateStore

    store = CandidateStore(str(tmp_path / "candidates.json"))
    candidate = store.submit_records([_record("memory-1"), _record("memory-2")])["candidates"][0]
    assert store.validate(candidate["id"])["success"] is True
    assert store.transition(candidate["id"], "canary", skill_name="candidate-skill")["success"] is True
    assert store.transition(candidate["id"], "canary")["success"] is False
    assert store.transition(candidate["id"], "active")["success"] is True
    assert store.transition(candidate["id"], "canary")["success"] is False
    assert store.transition(candidate["id"], "retired")["success"] is True
    assert store.transition(candidate["id"], "active")["success"] is False


def test_publishing_existing_canary_does_not_generate_a_second_skill(tmp_path, monkeypatch):
    """A repeated publish request is rejected before skill generation."""
    import l3.memory.r4_agent as r4_agent
    import l3.memory.r4_candidate_store as candidates
    from l1.kernel.skill import get_skill_manager, reset_skill_manager
    from l3.memory.r4_candidate_store import CandidateStore, publish_candidate

    calls = []

    class _FakeR4:
        def evolve_skill(self, **kwargs):
            calls.append(kwargs)
            get_skill_manager().create(
                "published-once",
                prompt="Bound candidate skill.",
                tags=["evolved"],
                binding=kwargs["binding"],
                status=kwargs["status"],
                internal=True,
            )
            return {"success": True, "skill": "published-once"}

    reset_skill_manager()
    monkeypatch.setattr(r4_agent, "get_r4_agent", lambda: _FakeR4())
    try:
        store = CandidateStore(str(tmp_path / "candidates.json"))
        candidate = store.submit_records([_record("memory-1"), _record("memory-2")])["candidates"][0]
        monkeypatch.setattr(candidates, "_store", store)

        first = publish_candidate(candidate["id"], "Create a build skill from validated evidence.")
        second = publish_candidate(candidate["id"], "Create another build skill from the same evidence.")

        assert first["success"] is True
        assert second["success"] is False
        assert "already published" in second["error"]
        assert len(calls) == 1
    finally:
        reset_skill_manager()


def test_activate_and_retire_keep_candidate_and_skill_in_sync(tmp_path, monkeypatch):
    """Concurrent activate and retire requests leave no injectable retired skill."""
    import l3.memory.r4_candidate_store as candidates
    from l1.kernel.skill import get_skill_manager, reset_skill_manager
    from l3.memory.r4_candidate_store import CandidateStore, activate_candidate, retire_candidate

    reset_skill_manager()
    try:
        store = CandidateStore(str(tmp_path / "candidates.json"))
        candidate = store.submit_records([_record("memory-1"), _record("memory-2")])["candidates"][0]
        assert store.validate(candidate["id"])["success"] is True
        assert store.transition(candidate["id"], "canary", skill_name="race-skill")["success"] is True
        get_skill_manager().create("race-skill", prompt="Bound candidate skill.", status="canary", internal=True)
        monkeypatch.setattr(candidates, "_store", store)

        active_update_started = threading.Event()
        release_active_update = threading.Event()
        retired_update_started = threading.Event()
        update = get_skill_manager().update

        def controlled_update(name, data, *args, **kwargs):
            if name == "race-skill" and data.get("status") == "active":
                active_update_started.set()
                assert release_active_update.wait(timeout=1)
            if name == "race-skill" and data.get("status") == "retired":
                retired_update_started.set()
            return update(name, data, *args, **kwargs)

        monkeypatch.setattr(get_skill_manager(), "update", controlled_update)
        activated: dict = {}
        retired: dict = {}
        activate_thread = threading.Thread(target=lambda: activated.update(activate_candidate(candidate["id"])))
        retire_thread = threading.Thread(target=lambda: retired.update(retire_candidate(candidate["id"])))

        activate_thread.start()
        assert active_update_started.wait(timeout=1)
        retire_thread.start()
        assert not retired_update_started.wait(timeout=0.1)
        release_active_update.set()
        activate_thread.join(timeout=1)
        retire_thread.join(timeout=1)

        assert not activate_thread.is_alive()
        assert not retire_thread.is_alive()
        assert activated["success"] is True
        assert retired["success"] is True
        assert store.get(candidate["id"])["state"] == "retired"
        assert get_skill_manager().get("race-skill")["status"] == "retired"
    finally:
        reset_skill_manager()


def test_publish_and_retire_do_not_leave_an_orphan_canary(tmp_path, monkeypatch):
    """Concurrent publication and retirement cannot leave an untracked canary skill."""
    import l3.memory.r4_agent as r4_agent
    import l3.memory.r4_candidate_store as candidates
    from l1.kernel.skill import get_skill_manager, reset_skill_manager
    from l3.memory.r4_candidate_store import CandidateStore, publish_candidate, retire_candidate

    evolve_started = threading.Event()
    release_evolve = threading.Event()
    retired_skill = threading.Event()

    class _BlockingR4:
        def evolve_skill(self, **kwargs):
            evolve_started.set()
            assert release_evolve.wait(timeout=1)
            get_skill_manager().create(
                "published-race-skill",
                prompt="Bound candidate skill.",
                tags=["evolved"],
                binding=kwargs["binding"],
                status=kwargs["status"],
                internal=True,
            )
            return {"success": True, "skill": "published-race-skill"}

    reset_skill_manager()
    monkeypatch.setattr(r4_agent, "get_r4_agent", lambda: _BlockingR4())
    try:
        store = CandidateStore(str(tmp_path / "candidates.json"))
        candidate = store.submit_records([_record("memory-1"), _record("memory-2")])["candidates"][0]
        monkeypatch.setattr(candidates, "_store", store)
        update = get_skill_manager().update

        def observed_update(name, data, *args, **kwargs):
            if name == "published-race-skill" and data.get("status") == "retired":
                retired_skill.set()
            return update(name, data, *args, **kwargs)

        monkeypatch.setattr(get_skill_manager(), "update", observed_update)
        published: dict = {}
        retired: dict = {}
        publish_thread = threading.Thread(
            target=lambda: published.update(publish_candidate(candidate["id"], "Build a candidate skill."))
        )
        retire_thread = threading.Thread(target=lambda: retired.update(retire_candidate(candidate["id"])))

        publish_thread.start()
        assert evolve_started.wait(timeout=1)
        retire_thread.start()
        assert store.get(candidate["id"])["state"] == "validated"
        release_evolve.set()
        publish_thread.join(timeout=1)
        retire_thread.join(timeout=1)

        assert not publish_thread.is_alive()
        assert not retire_thread.is_alive()
        assert published["success"] is True
        assert retired["success"] is True
        assert retired_skill.is_set()
        assert store.get(candidate["id"])["state"] == "retired"
        assert get_skill_manager().get("published-race-skill")["status"] == "retired"
    finally:
        reset_skill_manager()


def test_canary_with_cell_role_card_binding_is_not_filtered_by_agent_tag():
    """Explicit Cell/role/card scope remains injectable for any matching agent."""
    from l1.kernel.skill import get_skill_manager, reset_skill_manager
    from l3.memory.r4_agent import R4Agent

    reset_skill_manager()
    try:
        get_skill_manager().create(
            "cell-scoped-canary",
            prompt="Use the scoped candidate procedure.",
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

        allowed = R4Agent().get_evolved_skills(
            agent_id="agent-anonymous",
            cell_id="cell-build",
            role="builder",
            tags=["card:build"],
        )

        assert [skill["name"] for skill in allowed] == ["cell-scoped-canary"]
    finally:
        reset_skill_manager()
