"""Identity registry completeness tests — persistence + config overrides.

Covers the gap-fill for the identity registration system:
  - bindings survive restarts (persist/restore roundtrip)
  - identity_roles.yaml keyword overrides take precedence in match_identity
  - registry is fully config-driven (no hardcoded behavior beyond defaults)
"""

from __future__ import annotations

import json
import threading

import pytest

from l1.kernel.identity_binding import (
    IdentityBindingManager,
    get_identity_binding_manager,
    reset_identity_binding_manager,
)


@pytest.fixture(autouse=True)
def _clean():
    from l3.agent import prompts as _prompts

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


def test_concurrent_bind_unbind_restores_parseable_final_state(tmp_path):
    """Concurrent mutations leave a parseable state matching the final bindings."""
    state = str(tmp_path / "identity_bindings.json")
    manager = IdentityBindingManager(state_path=state)
    worker_count = 12
    start = threading.Barrier(worker_count)
    errors: list[str] = []

    def mutate(index: int) -> None:
        """Bind one unique role, then remove alternating roles."""
        try:
            start.wait()
            role = f"role-{index}"
            assert manager.bind("cell-1", role, f"fragment-{index}", internal=True)["success"]
            if index % 2:
                assert manager.unbind("cell-1", role, internal=True)["success"]
        except Exception as error:
            errors.append(str(error))

    threads = [threading.Thread(target=mutate, args=(index,)) for index in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    data = json.loads((tmp_path / "identity_bindings.json").read_text(encoding="utf-8"))
    restored = IdentityBindingManager(state_path=state)
    expected_roles = {f"role-{index}" for index in range(worker_count) if not index % 2}
    assert set(data["cell-1"]) == expected_roles
    assert set(restored.bindings_for_cell("cell-1")) == expected_roles


def test_two_managers_merge_concurrent_persistence_without_losing_bindings(tmp_path):
    """Managers sharing a state path retain both independently committed bindings."""
    state = str(tmp_path / "identity_bindings.json")
    first = IdentityBindingManager(state_path=state)
    second = IdentityBindingManager(state_path=state)
    start = threading.Barrier(2)
    errors: list[str] = []

    def bind_with(manager: IdentityBindingManager, role: str) -> None:
        """Publish a binding after both managers have loaded the same state."""
        try:
            start.wait()
            assert manager.bind("cell-1", role, f"fragment-{role}", internal=True)["success"]
        except Exception as error:
            errors.append(str(error))

    threads = [
        threading.Thread(target=bind_with, args=(first, "first-role")),
        threading.Thread(target=bind_with, args=(second, "second-role")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    restored = IdentityBindingManager(state_path=state)
    first_binding = restored.get_binding("cell-1", "first-role")
    second_binding = restored.get_binding("cell-1", "second-role")
    assert first_binding is not None
    assert first_binding.prompt_fragment == "fragment-first-role"
    assert second_binding is not None
    assert second_binding.prompt_fragment == "fragment-second-role"


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
    from l3.agent.prompts import load_prompt_overrides
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
