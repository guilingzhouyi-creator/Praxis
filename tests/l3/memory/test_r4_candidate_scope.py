"""R4 candidate skill lifecycle and binding retrieval tests."""

from __future__ import annotations


def test_canary_skill_injects_only_for_its_binding():
    """A canary skill is visible only to its target Cell, role, and card type."""
    from l1.kernel.skill import get_skill_manager, reset_skill_manager
    from l3.memory.r4_agent import R4Agent

    reset_skill_manager()
    try:
        get_skill_manager().create(
            "candidate-build-skill",
            prompt="Use the candidate build procedure.",
            tags=["evolved", "card:build"],
            status="canary",
            binding={
                "cell_ids": ["cell-build"],
                "roles": ["builder"],
                "agent_ids": ["agent-builder"],
                "card_natures": ["build"],
                "postures": ["productive"],
            },
            internal=True,
        )
        r4 = R4Agent()

        allowed = r4.get_evolved_skills(
            agent_id="agent-builder",
            cell_id="cell-build",
            role="builder",
            tags=["card:build"],
        )
        blocked = r4.get_evolved_skills(
            agent_id="agent-reviewer",
            cell_id="cell-review",
            role="reviewer",
            tags=["card:review"],
        )

        assert [skill["name"] for skill in allowed] == ["candidate-build-skill"]
        assert blocked == []
    finally:
        reset_skill_manager()


def test_draft_skill_never_enters_r4_retrieval():
    """Draft skill metadata persists in the registry but is not injectable."""
    from l1.kernel.skill import get_skill_manager, reset_skill_manager
    from l3.memory.r4_agent import R4Agent

    reset_skill_manager()
    try:
        get_skill_manager().create(
            "draft-skill",
            prompt="This must not inject yet.",
            tags=["evolved"],
            status="draft",
            binding={"cell_ids": ["cell-build"]},
            internal=True,
        )

        assert R4Agent().get_evolved_skills(cell_id="cell-build") == []
    finally:
        reset_skill_manager()


def test_skill_binding_and_status_round_trip_from_markdown(tmp_path):
    """Skill frontmatter restores lifecycle and binding fields after reload."""
    from l1.kernel.skill import get_skill_manager, reset_skill_manager

    skill_dir = tmp_path / "candidate-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: candidate-skill\n"
        "description: Use when validating candidate scope\n"
        "tags: [evolved]\n"
        "posture: productive\n"
        "status: canary\n"
        "binding:\n"
        "  cell_ids: [cell-build]\n"
        "  roles: [builder]\n"
        "  agent_ids: [agent-builder]\n"
        "  card_natures: [build]\n"
        "  postures: [productive]\n"
        "---\n"
        "Candidate body\n",
        encoding="utf-8",
    )
    reset_skill_manager()
    try:
        get_skill_manager().load_dir(str(tmp_path))
        skill = get_skill_manager().get("candidate-skill")
        assert skill["status"] == "canary"
        assert skill["binding"]["roles"] == ["builder"]
    finally:
        reset_skill_manager()


def test_r4_persistence_retains_canary_binding(tmp_path, monkeypatch):
    """R4's writer preserves lifecycle metadata through a reload."""
    from l1.kernel.paths import get_paths
    from l1.kernel.skill import get_skill_manager, reset_skill_manager
    from l3.memory.r4_agent import R4Agent

    paths = get_paths()
    monkeypatch.setattr(paths, "skill_project_evolved_dir", str(tmp_path / "evolved"))
    reset_skill_manager()
    try:
        r4 = R4Agent()
        r4._persist_skill_md(
            name="persisted-canary",
            description="Use when checking candidate persistence",
            prompt="Scoped canary content.",
            tags=["evolved"],
            binding={"cell_ids": ["cell-build"], "postures": ["productive"]},
            status="canary",
            scope="project",
        )
        get_skill_manager().load_dir(paths.skill_project_evolved_dir)
        persisted = get_skill_manager().get("persisted-canary")

        assert persisted["status"] == "canary"
        assert persisted["binding"]["cell_ids"] == ["cell-build"]
    finally:
        reset_skill_manager()
