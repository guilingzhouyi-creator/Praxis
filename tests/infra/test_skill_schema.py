"""Skill catalog schema conformance — normalization gate for config/skills.

Enforces the normalized frontmatter contract across every builtin SKILL.md:
required fields, enum validity, dangling ``next``/``dependencies`` references,
guidance-DAG acyclicity and loader round-trip of the new fields
(disclosure/stages/next). This gate makes future catalog edits conform
instead of drifting — the enforcement half of the skill-file normalization.
"""

from __future__ import annotations

import glob
import os

import pytest
import yaml

from l1.kernel.skill import get_skill_manager, reset_skill_manager

SKILLS_DIR = "config/skills"

AUDIENCE_TAGS = {"strategy", "execution"}
DISCLOSURE_VALUES = {"full", "index", "none"}
POSTURE_VALUES = {"productive", "offensive"}


def _skill_files() -> list[str]:
    """All builtin SKILL.md files under config/skills (sorted)."""
    return sorted(glob.glob(f"{SKILLS_DIR}/*/SKILL.md"))


def _frontmatter(path: str) -> dict:
    """Parse the YAML frontmatter of a SKILL.md file."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    parts = text.split("---", 2)
    assert len(parts) > 1, f"{path}: missing frontmatter delimiters"
    return yaml.safe_load(parts[1]) or {}


@pytest.fixture(autouse=True)
def _reset_and_load():
    """Fresh SkillManager with the real builtin catalog for every test."""
    reset_skill_manager()
    get_skill_manager().load_dir(SKILLS_DIR)
    yield
    reset_skill_manager()


class TestSchemaRequiredFields:
    """Every builtin skill must declare the full normalized frontmatter."""

    REQUIRED = (
        "name",
        "description",
        "tags",
        "disable-model-invocation",
        "posture",
        "allowed-tools",
        "disclosure",
    )

    @pytest.mark.parametrize("path", _skill_files(), ids=lambda p: os.path.basename(os.path.dirname(p)))
    def test_required_fields_present(self, path):
        meta = _frontmatter(path)
        for field in self.REQUIRED:
            assert field in meta, f"{path}: missing '{field}'"

    @pytest.mark.parametrize("path", _skill_files(), ids=lambda p: os.path.basename(os.path.dirname(p)))
    def test_enum_validity(self, path):
        meta = _frontmatter(path)
        assert meta["posture"] in POSTURE_VALUES, f"{path}: bad posture '{meta['posture']}'"
        assert meta["disclosure"] in DISCLOSURE_VALUES, f"{path}: bad disclosure '{meta['disclosure']}'"
        audience = set(meta.get("tags") or []) & AUDIENCE_TAGS
        assert len(audience) <= 1, f"{path}: conflicting audience tags {audience}"

    @pytest.mark.parametrize("path", _skill_files(), ids=lambda p: os.path.basename(os.path.dirname(p)))
    def test_description_trigger_oriented(self, path):
        desc = _frontmatter(path)["description"]
        assert desc.startswith("Use when"), f"{path}: description must be trigger-oriented ('Use when …')"

    @pytest.mark.parametrize("path", _skill_files(), ids=lambda p: os.path.basename(os.path.dirname(p)))
    def test_name_matches_directory(self, path):
        meta = _frontmatter(path)
        assert meta["name"] == os.path.basename(os.path.dirname(path)), f"{path}: name ≠ directory"


class TestSchemaReferences:
    """next/dependencies must reference skills that actually exist."""

    def test_no_dangling_references(self):
        sm = get_skill_manager()
        known = {s["name"] for s in sm.list_skills()}
        for path in _skill_files():
            meta = _frontmatter(path)
            for ref in list(meta.get("dependencies") or []) + list(meta.get("next") or []):
                assert ref in known, f"{path}: dangling reference '{ref}'"

    def test_guidance_graph_acyclic(self):
        r = get_skill_manager().validate_guidance_graph()
        assert r["acyclic"] is True, f"guidance graph cycles: {r['cycles']}"


class TestSchemaRoundTrip:
    """Loader round-trip preserves the normalized fields."""

    def test_full_frontmatter_round_trip(self, tmp_path):
        skill_dir = tmp_path / "rt-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: rt-skill\n"
            "description: Use when testing round-trip\n"
            "tags: [execution]\n"
            "disable-model-invocation: true\n"
            "posture: productive\n"
            "disclosure: index\n"
            "allowed-tools: [read_file]\n"
            "next: [code-review]\n"
            "stages:\n"
            "  - id: one\n"
            "    instructions: do one\n"
            "scope: cell\n"
            "scope-identity: cell-alpha\n"
            "priority: 3\n"
            "---\n"
            "body\n",
            encoding="utf-8",
        )
        sm = get_skill_manager()
        sm.load_dir(str(tmp_path))
        skill = sm.get("rt-skill")
        assert skill["disclosure"] == "index"
        assert skill["next"] == ["code-review"]
        assert skill["stages"][0]["id"] == "one"
        # Declarative scope/priority round-trip: scope + identity are
        # preserved and mapped into the runtime binding so the existing
        # skill_is_injectable filter applies unchanged.
        assert skill["scope"] == "cell"
        assert skill["scope_identity"] == "cell-alpha"
        assert skill["priority"] == 3
        binding = skill.get("binding") or {}
        assert binding.get("cell_ids") == ["cell-alpha"]


class TestRegisterAndCadence:
    """Registration persistence, enable/disable, and update cadence control."""

    def test_register_persists_to_custom_tier(self):
        """Registering a custom skill writes SKILL.md into the custom dir."""
        import os

        from l1.kernel.paths import get_paths as _gp
        from l3.memory.r4_agent import get_r4_agent

        name = "reg-persist-test"
        sm = get_skill_manager()
        sm.delete(name, agent_id="dev", role="l3")
        result = get_r4_agent().register_custom_skill(
            name=name,
            description="Use when testing register persistence",
            prompt="do the thing",
            tags=["execution"],
            scope="cell",
            scope_identity="cell-reg",
            priority=4,
            agent_id="dev",
            role="l3",
        )
        assert result.get("success"), result
        skill = sm.get(name)
        assert skill is not None
        assert "custom" in skill.get("tags", [])
        assert skill.get("scope") == "cell"
        assert skill.get("scope_identity") == "cell-reg"
        md = os.path.join(_gp().skill_custom_dir, name, "SKILL.md")
        assert os.path.isfile(md), f"expected persisted SKILL.md at {md}"
        sm.delete(name, agent_id="dev", role="l3")

    def test_disable_then_enable_status(self):
        """Disable flips status to retired; enable restores active."""
        sm = get_skill_manager()
        name = "reg-toggle-test"
        created = sm.create(
            name,
            description="Use when testing toggle",
            prompt="body",
            tags=["custom"],
            agent_id="dev",
            role="l3",
        )
        assert created.get("success"), created
        disabled = sm.update(name, {"status": "retired"}, agent_id="dev", role="l3")
        assert disabled.get("success"), disabled
        assert not sm.skill_is_injectable(sm.get(name), agent_id="dev", role="l3")
        enabled = sm.update(name, {"status": "active"}, agent_id="dev", role="l3")
        assert enabled.get("success"), enabled
        assert sm.skill_is_injectable(sm.get(name), agent_id="dev", role="l3")
        sm.delete(name, agent_id="dev", role="l3")

    def test_update_policy_controls_cadence(self):
        """set_update_policy fast|slow + enabled persists on the manager."""
        sm = get_skill_manager()
        fast = sm.set_update_policy(update_speed="fast", enabled=True, source="test")
        assert fast.get("success") and fast.get("update_speed") == "fast"
        slow = sm.set_update_policy(update_speed="slow", enabled=False, source="test")
        assert slow.get("success") and slow.get("update_speed") == "slow" and slow.get("enabled") is False
        policy = sm.update_policy()
        assert policy.get("update_speed") == "slow" and policy.get("enabled") is False
        invalid = sm.set_update_policy(update_speed="bogus", source="test")
        assert not invalid.get("success")
        sm.set_update_policy(update_speed="fast", enabled=True, source="reset")


class TestSchemaBodyLayout:
    """Body section contract: Constitution Binding / Rules / Procedures present
    and parseable; universal principles live only in the shared layer."""

    def test_required_body_sections(self):
        for path in _skill_files():
            with open(path, encoding="utf-8") as f:
                body = f.read()
            assert "## Constitution Binding" in body, f"{path}: missing Constitution Binding"
            assert "## Rules" in body, f"{path}: missing Rules section"
            assert "## Procedures" in body, f"{path}: missing Procedures section"

    def test_no_universal_principles_residue(self):
        for path in _skill_files():
            with open(path, encoding="utf-8") as f:
                body = f.read()
            assert "## Universal Principles" not in body, f"{path}: principles must live in config/skills/_shared/"

    def test_rules_and_procedures_parse(self):
        sm = get_skill_manager()
        for path in _skill_files():
            name = os.path.basename(os.path.dirname(path))
            skill = sm.get(name)
            assert skill is not None, f"{path}: not loaded"
            assert skill.get("rules"), f"{path}: no parseable rules"
            assert skill.get("procedures"), f"{path}: no parseable procedures"
