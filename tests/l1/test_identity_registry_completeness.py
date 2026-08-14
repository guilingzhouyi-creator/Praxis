"""Identity registry completeness tests — persistence + config overrides.

Covers the gap-fill for the identity registration system:
  - bindings survive restarts (persist/restore roundtrip)
  - identity_roles.yaml keyword overrides take precedence in match_identity
  - registry is fully config-driven (no hardcoded behavior beyond defaults)
"""

from __future__ import annotations

import pytest

from l1.kernel.identity_binding import (
    IdentityBindingManager,
    get_identity_binding_manager,
    reset_identity_binding_manager,
)


@pytest.fixture(autouse=True)
def _clean():
    from l1.kernel import prompts as _prompts

    reset_identity_binding_manager()
    _saved = dict(_prompts._overrides)
    yield
    reset_identity_binding_manager()
    _prompts._overrides.clear()
    _prompts._overrides.update(_saved)


def test_persist_restore_roundtrip(tmp_path):
    """Bindings written to disk are restored by a fresh manager instance."""
    state = str(tmp_path / "identity_bindings.json")
    m1 = IdentityBindingManager(state_path=state)
    m1.bind("cell-1", "tester", "You are the testing expert.", domain_tags=["test"], internal=True)

    # Fresh instance reads the same file — simulates a restart.
    m2 = IdentityBindingManager(state_path=state)
    binding = m2.get_binding("cell-1", "tester")
    assert binding is not None
    assert binding.prompt_fragment == "You are the testing expert."
    assert binding.domain_tags == ["test"]


def test_persist_after_unbind(tmp_path):
    """Unbind persists the removal (restart does not resurrect it)."""
    state = str(tmp_path / "identity_bindings.json")
    m1 = IdentityBindingManager(state_path=state)
    m1.bind("cell-1", "writer", "You write code.", internal=True)
    m1.unbind("cell-1", "writer", internal=True)

    m2 = IdentityBindingManager(state_path=state)
    assert m2.get_binding("cell-1", "writer") is None


def test_restore_missing_file_is_empty():
    """No state file → empty registry without raising."""
    m = IdentityBindingManager(state_path="/nonexistent/dir/never.json")
    assert m.cell_ids() == []
    assert m.revision() == 0


def test_restore_tolerates_corrupt_file(tmp_path):
    """A corrupt state file degrades to an empty registry (best-effort)."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    m = IdentityBindingManager(state_path=str(bad))
    assert m.cell_ids() == []


def test_identity_roles_config_override(tmp_path, monkeypatch):
    """praxis.yaml prompts: overrides win over the built-in match keywords."""
    from l1.kernel.prompts import load_prompt_overrides
    from l3.bus.htn_planner import match_identity

    # Simulate the praxis.yaml prompts: section loading (the sanctioned
    # config-driven override surface for prompt-registry data).
    load_prompt_overrides({"identity": {"match": {"build": "fabricate|construct"}}})

    # "fabricate" only matches via the override, not the built-in keywords.
    assert match_identity("fabricate the module") == "build"
    # Prompt-registry default still works for identities without overrides.
    assert match_identity("run the test suite", domain="test") == "test"


def test_registry_is_memory_and_persistent():
    """The singleton persists to the data-dir identity_bindings.json."""
    mgr = get_identity_binding_manager()
    assert mgr._state_path.endswith("identity_bindings.json")
