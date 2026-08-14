"""Phase-2A tests — generic three-identity fields (build/test/review).

Covers:
  A1  constants in params + identity_roles.yaml override surface
  A2  htn_planner.match_identity intent→identity dispatch
  A3  IdentityBindingManager.identity_set_for agent identity-set resolution
"""

from __future__ import annotations

import pytest

from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager
from l1.kernel.params.agent import IDENTITY_BUILD, IDENTITY_DEFAULT_SET, IDENTITY_FIELDS, IDENTITY_REVIEW, IDENTITY_TEST


@pytest.fixture(autouse=True)
def _clean():
    from l1.kernel import prompts as _prompts

    reset_identity_binding_manager()
    _saved = dict(_prompts._overrides)
    yield
    reset_identity_binding_manager()
    _prompts._overrides.clear()
    _prompts._overrides.update(_saved)


# ── A1: constants ──


def test_three_identity_constants():
    """The three generic identity fields exist and are canonical."""
    assert IDENTITY_FIELDS == (IDENTITY_BUILD, IDENTITY_TEST, IDENTITY_REVIEW)
    assert IDENTITY_FIELDS == ("build", "test", "review")
    assert IDENTITY_DEFAULT_SET == IDENTITY_FIELDS


def test_identity_roles_yaml_present():
    """config/discovery/identity_roles.yaml exists for overrides."""
    from pathlib import Path

    p = Path("config/discovery/identity_roles.yaml")
    assert p.exists()


# ── A2: match_identity ──


def test_match_identity_build():
    from l3.bus.htn_planner import match_identity

    assert match_identity("implement the login feature") == "build"
    assert match_identity("refactor the allocator") == "build"


def test_match_identity_test():
    from l3.bus.htn_planner import match_identity

    assert match_identity("run the unit test suite") == "test"
    assert match_identity("verify coverage") == "test"


def test_match_identity_review():
    from l3.bus.htn_planner import match_identity

    assert match_identity("review the pull request") == "review"
    assert match_identity("audit the gatechain changes") == "review"


def test_match_identity_none():
    from l3.bus.htn_planner import match_identity

    assert match_identity("hello world greeting") == ""


def test_match_identity_domain_hint():
    """A domain hint routes ambiguous intents (e.g. 'test' domain → test)."""
    from l3.bus.htn_planner import match_identity

    assert match_identity("check the pipeline", domain="test") == "test"


# ── A3: identity_set_for ──


def test_identity_set_default_full():
    """No binding → full default identity set (build/test/review)."""
    mgr = get_identity_binding_manager()
    assert mgr.identity_set_for("cell-1", "writer") == IDENTITY_DEFAULT_SET


def test_identity_set_narrowed_by_domain_tags():
    """A binding whose domain_tags name identity fields narrows the set."""
    mgr = get_identity_binding_manager()
    mgr.bind("cell-1", "tester", "You are the test identity.", domain_tags=["test"], internal=True)
    assert mgr.identity_set_for("cell-1", "tester") == ("test",)


def test_identity_set_ignores_non_identity_tags():
    """domain_tags without identity fields fall back to the full set."""
    mgr = get_identity_binding_manager()
    mgr.bind("cell-1", "writer", "You write code.", domain_tags=["codegen"], internal=True)
    assert mgr.identity_set_for("cell-1", "writer") == IDENTITY_DEFAULT_SET


def test_identity_set_partial_union():
    """Multiple identity tags produce the union subset."""
    mgr = get_identity_binding_manager()
    mgr.bind("cell-1", "fullstack", "Dual identity.", domain_tags=["build", "review"], internal=True)
    assert mgr.identity_set_for("cell-1", "fullstack") == ("build", "review")
