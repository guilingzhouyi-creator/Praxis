"""Tests for sensitive-path merge hunk auditing."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "py" / "audit_merge_hunks.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("audit_merge_hunks", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "merge-test")
    (repo / "docs" / "roadmaps").mkdir(parents=True)
    (repo / "config" / "discovery").mkdir(parents=True)
    (repo / "docs" / "roadmaps" / "one.md").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (repo / "config" / "discovery" / "one.yaml").write_text("value: one\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "chore: seed sensitive files")
    return repo


def test_hunk_parser_counts_changes_and_ignores_headers(tmp_path: Path):
    repo = _repo(tmp_path)
    _git(repo, "switch", "-q", "-c", "feature/hunk-counts")
    (repo / "docs" / "roadmaps" / "one.md").write_text("one\nchanged\nthree\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "docs(roadmaps): count one hunk")
    module = _load_script()
    module.ROOT = repo
    audits = module.audit("main", "feature/hunk-counts")
    assert len(audits) == 1
    assert audits[0].path == "docs/roadmaps/one.md"
    assert len(audits[0].hunks) == 1
    assert audits[0].hunks[0].additions == 1
    assert audits[0].hunks[0].deletions == 1


def test_whole_file_replacement_is_rejected(tmp_path: Path, monkeypatch):
    repo = _repo(tmp_path)
    _git(repo, "switch", "-q", "-c", "feature/replace")
    (repo / "docs" / "roadmaps" / "one.md").write_text("replacement\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "docs(roadmaps): replace snapshot")
    module = _load_script()
    monkeypatch.setattr(module, "ROOT", repo)
    assert module.main(["--base", "main", "--head", "feature/replace", "--check"]) == 1


def test_small_hunk_change_passes_check(tmp_path: Path):
    repo = _repo(tmp_path)
    _git(repo, "switch", "-q", "-c", "feature/hunk")
    (repo / "docs" / "roadmaps" / "one.md").write_text("one\nupdated\nthree\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "docs(roadmaps): update one hunk")
    module = _load_script()
    module.ROOT = repo
    assert module.main(["--base", "main", "--head", "feature/hunk", "--check"]) == 0
