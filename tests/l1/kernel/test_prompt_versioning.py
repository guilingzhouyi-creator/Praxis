"""Tests for system-prompt versioning (3.2, P1-⑤)."""

from __future__ import annotations

import importlib


def _reload_prompts():
    import l1.kernel.prompts as p

    importlib.reload(p)
    return p


def test_load_records_versions():
    p = _reload_prompts()
    p.load_prompt_overrides({"ver.test1": "v1 text"})
    p.load_prompt_overrides({"ver.test1": "v2 text"})
    assert p.prompt_versions()["versions"].get("ver.test1") == 2


def test_rollback_restores_snapshot():
    p = _reload_prompts()
    p.load_prompt_overrides({"ver.test2": "v1 text"})
    p.load_prompt_overrides({"ver.test2": "v2 text"})
    r = p.rollback_prompt("ver.test2", 1)
    assert r["success"] is True
    assert p.get_prompt("ver.test2", "") == "v1 text"


def test_rollback_unknown_version_fails():
    p = _reload_prompts()
    p.load_prompt_overrides({"ver.test3": "v1 text"})
    r = p.rollback_prompt("ver.test3", 99)
    assert r["success"] is False


def test_versioning_switch():
    p = _reload_prompts()
    p.set_prompt_versioning(enabled=False)
    assert p.prompt_versioning_status()["enabled"] is False
    # Disabled: load does not track versions.
    p.load_prompt_overrides({"ver.test4": "v1 text"})
    assert "ver.test4" not in p.prompt_versions()["versions"]
    p.set_prompt_versioning(enabled=True)


def test_rollback_creates_new_revision():
    p = _reload_prompts()
    p.load_prompt_overrides({"ver.test5": "v1 text"})
    p.load_prompt_overrides({"ver.test5": "v2 text"})
    r = p.rollback_prompt("ver.test5", 1)
    assert r["version"] == 3  # rollback itself is a new revision
