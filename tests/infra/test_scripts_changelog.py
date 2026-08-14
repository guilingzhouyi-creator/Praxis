"""Tests for scripts/py/generate_changelog.py and bump-version CHANGELOG migration.

Covers the Pure-functions of the changelog tooling: Conventional-Commits
grouping, the [Unreleased] render, and the bump-time [Unreleased] -> version
migration. Scripts have hyphens, so they are loaded by path with importlib.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "py"))


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "py" / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


generate_changelog = _load("generate_changelog", "generate_changelog.py")
bump_version = _load("bump_version", "bump_version.py")


def test_group_subjects_by_type():
    subs = ["feat(core): add ring", "fix: fix leak", "docs(api): update", "chore: noise", "Merge branch"]
    g = generate_changelog.group_subjects(subs)
    assert "新增" in g and "修复" in g and "文档" in g and "变更" in g  # chore -> 变更
    for items in g.values():
        for s in items:
            assert "Merge" not in s


def test_group_skips_non_conventional():
    g = generate_changelog.group_subjects(["random line", "feat(a): b"])
    assert g["新增"] == ["- **Feat (a)**: b"]


def test_render_empty_and_nonempty():
    empty = generate_changelog.render({})
    assert "## [Unreleased]" in empty and "无类型化提交" in empty
    nonempty = generate_changelog.render({"新增": ["- **Feat**: x"]})
    assert "- **Feat**: x" in nonempty


def test_migrate_changelog_moves_unreleased(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "## [Unreleased]\n\n### 新增\n- x\n\n## [0.4.1] - 2026-08-07\n\n### 新增\n- old\n",
        encoding="utf-8",
    )
    original = bump_version.CHANGELOG
    bump_version.CHANGELOG = changelog  # type: ignore[assignment]
    try:
        changes: list[str] = []
        bump_version._migrate_changelog("0.5.0", False, changes)
        out = changelog.read_text(encoding="utf-8")
        head = out.split("## [0.4.1]")[0]
        assert "## [0.5.0] - " in head
        assert "- x" in head  # migrated from [Unreleased]
        assert "## [Unreleased]" in out  # reopened empty
        today = _dt.date.today().isoformat()
        assert changes == [f"CHANGELOG.md: [Unreleased] -> [0.5.0 - {today}]"]
    finally:
        bump_version.CHANGELOG = original  # type: ignore[assignment]
