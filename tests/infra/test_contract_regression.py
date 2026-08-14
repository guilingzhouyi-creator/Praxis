"""Contract regression guards — public shapes that refactors must not break.

Locks the runtime-facing contracts that silently drifted in past refactors
(use_skill structured view, list_skills external view, split-module symbol
locations). These tests fail fast when a refactor changes a public shape
without updating the consumers that rely on it.

Covered contracts:
  - use_skill default (structured) view: rules/procedures/stages, no prompt
  - use_skill full view: write-gated privileged read
  - list_skills external view: prompt stripped, rules/procedures as counts
  - split-module symbol homes (MemEntry, LSP_RESPONSE_TIMEOUT, structured_skill)
"""

from __future__ import annotations

from l1.kernel.skill import get_skill_manager, reset_skill_manager
from l3.tools._skills import use_skill

STRUCTURED_KEYS = (
    "success",
    "skill",
    "name",
    "description",
    "rules",
    "procedures",
    "allowed_tools",
    "variables",
    "dependencies",
    "next",
    "disclosure",
    "stage",
)


def _load_builtins() -> None:
    """Fresh SkillManager with the real builtin catalog."""
    reset_skill_manager()
    get_skill_manager().load_dir("config/skills")


class TestUseSkillStructuredViewContract:
    """use_skill defaults to the structured agent-facing view (no body)."""

    def test_structured_keys_present(self):
        _load_builtins()
        r = use_skill({"name": "kernel"}, "l3a")
        assert r["success"], r
        for key in STRUCTURED_KEYS:
            assert key in r, f"use_skill structured view missing key: {key}"

    def test_structured_view_has_no_prompt(self):
        _load_builtins()
        r = use_skill({"name": "kernel"}, "l3a")
        assert "prompt" not in r, "structured view must not expose the markdown body"

    def test_rules_and_procedures_are_lists(self):
        _load_builtins()
        r = use_skill({"name": "tdd"}, "agent-http")
        assert r["success"], r
        assert isinstance(r["rules"], list)
        assert isinstance(r["procedures"], list)

    def test_full_mode_requires_write_identity(self):
        _load_builtins()
        r = use_skill({"name": "kernel", "full": True}, "l3a")
        # No _agent_id/_role supplied → the write gate refuses.
        assert not r["success"]
        assert "permission" in r.get("error", "").lower()


class TestListSkillsExternalViewContract:
    """list_skills strips prompt; rules/procedures surface as counts."""

    def test_external_view_drops_prompt(self):
        _load_builtins()
        skills = get_skill_manager().list_skills()
        assert skills
        for s in skills:
            assert s.get("prompt", "MISSING") == "", "prompt must be stripped on the external view"
            assert isinstance(s.get("rules"), int), "rules exposed as a count on the external view"
            assert isinstance(s.get("procedures"), int), "procedures exposed as a count on the external view"

    def test_internal_view_can_include_prompt(self):
        _load_builtins()
        skills = get_skill_manager().list_skills(include_prompt=True)
        assert skills
        assert any(s.get("prompt") for s in skills), "internal retrieval may pass include_prompt=True"


class TestSplitModuleSymbolLocations:
    """Symbols relocated by module splits stay at their new homes."""

    def test_mem_entry_lives_in_memory_ring(self):
        from l3.memory.memory_ring import MemEntry

        assert MemEntry is not None

    def test_lsp_timeout_lives_in_params_api(self):
        from l1.kernel.params.api import LSP_RESPONSE_TIMEOUT

        assert isinstance(LSP_RESPONSE_TIMEOUT, float)

    def test_structured_skill_lives_in_skill_retrieval(self):
        from l1.kernel.skill_retrieval import SkillRetrievalMixin

        assert callable(SkillRetrievalMixin.structured_skill)
