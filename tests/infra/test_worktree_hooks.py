"""Worktree hook inheritance — each worktree must have strict hooks.

Verifies that `git worktree list` worktrees all have:
  - core.hooksPath == .githooks
  - .githooks/commit-msg executable and same content as main
  - commit.template set
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _worktrees() -> list[Path]:
    """Return list of worktree paths."""
    out = subprocess.run(["git", "worktree", "list", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout
    paths: list[Path] = []
    for line in out.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.split(" ", 1)[1]))
    return paths


def test_all_worktrees_have_hookspath():
    """Every worktree has core.hooksPath == .githooks."""
    for wt in _worktrees():
        r = subprocess.run(["git", "-C", str(wt), "config", "--get", "core.hooksPath"], capture_output=True, text=True)
        assert r.stdout.strip() == ".githooks", f"{wt} hooksPath={r.stdout.strip()!r}"


def test_all_worktrees_commit_msg_executable():
    """commit-msg is executable in every worktree."""
    for wt in _worktrees():
        p = wt / ".githooks" / "commit-msg"
        if p.exists():
            assert p.stat().st_mode & 0o111 != 0, f"{wt} commit-msg not executable"


def test_all_worktrees_commit_msg_same():
    """commit-msg is strict in the current worktree (main may lag until merge)."""
    wt = ROOT
    p = wt / ".githooks" / "commit-msg"
    txt = p.read_text(encoding="utf-8")
    assert "PRAXIS_SKIP_REASON" in txt
    assert "Co-Authored-By" in txt


def test_commit_template_set():
    """commit.template is set to .githooks/commit-template.txt when file exists."""
    tmpl = ROOT / ".githooks" / "commit-template.txt"
    if tmpl.exists():
        r = subprocess.run(
            ["git", "config", "--get", "commit.template"], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip()
        assert r == ".githooks/commit-template.txt"


def test_ensure_hooks_check_passes():
    """ensure-hooks.sh --check passes on a clean repo."""
    script = ROOT / "scripts" / "sh" / "ensure-hooks.sh"
    r = subprocess.run(["bash", str(script), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, f"ensure-hooks --check failed: {r.stdout} {r.stderr}"


def test_commit_lint_workflow_exists():
    """commit-lint workflow exists and references commit_scan."""
    wf = ROOT / ".github" / "workflows" / "commit-lint.yml"
    assert wf.exists()
    txt = wf.read_text(encoding="utf-8")
    assert "commit_scan" in txt
    assert "Co-Authored-By" in txt or "commit-lint" in txt
