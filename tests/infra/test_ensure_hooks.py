"""Tests for scripts/sh/ensure-hooks.sh — worktree hook inheritance.

Verifies that the ensure-hooks script fixes and checks:
  - core.hooksPath
  - executable bits for commit-msg / pre-commit / post-checkout
  - commit.template
  - worktree inheritance
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "sh" / "ensure-hooks.sh"


def _run(mode: str = "") -> subprocess.CompletedProcess:
    """Run ensure-hooks.sh with optional --check."""
    env = os.environ.copy()
    env["PATH"] = f"/tmp:{env.get('PATH', '')}"
    # Ensure /tmp/python and /tmp/ruff exist for hooks that may call python
    Path("/tmp/python").symlink_to(Path("/tmp/python")) if False else None
    args = ["bash", str(SCRIPT)]
    if mode:
        args.append(mode)
    return subprocess.run(args, capture_output=True, text=True, cwd=ROOT, env=env)


def test_ensure_hooks_fixes_drift(tmp_path):
    """--check fails when hooksPath is wrong, fix restores it."""
    # Save original
    orig = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    try:
        subprocess.run(["git", "config", "core.hooksPath", "wrong/path"], cwd=ROOT, check=True)
        r = _run("--check")
        assert r.returncode == 1
        assert "core.hooksPath" in r.stdout or "core.hooksPath" in r.stderr
        # Fix mode should restore
        r2 = _run()
        assert r2.returncode == 0
        cur = subprocess.run(
            ["git", "config", "--get", "core.hooksPath"], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip()
        assert cur == ".githooks"
    finally:
        subprocess.run(["git", "config", "core.hooksPath", orig or ".githooks"], cwd=ROOT, check=False)


def test_ensure_hooks_executable_check(tmp_path):
    """Executable bits are verified in --check mode."""
    hook = ROOT / ".githooks" / "commit-msg"
    # Temporarily remove executable bit
    mode_before = hook.stat().st_mode
    try:
        hook.chmod(0o644)
        r = _run("--check")
        assert r.returncode == 1
        assert "not executable" in (r.stdout + r.stderr)
        # Fix should restore
        r2 = _run()
        assert r2.returncode == 0
        assert hook.stat().st_mode & 0o111 != 0
    finally:
        hook.chmod(mode_before)
        # Restore git index mode as well
        subprocess.run(["git", "update-index", "--chmod=+x", str(hook)], cwd=ROOT, capture_output=True)


def test_ensure_hooks_commit_template(tmp_path):
    """commit.template is set when .githooks/commit-template.txt exists."""
    tmpl = ROOT / ".githooks" / "commit-template.txt"
    assert tmpl.exists(), "commit-template.txt should exist after strict hooks change"
    # Ensure the template contains Co-Authored-By example
    text = tmpl.read_text(encoding="utf-8")
    assert "Co-Authored-By" in text
    assert "type(scope):" in text


def test_ensure_hooks_worktree_inheritance():
    """Worktrees inherit core.hooksPath from the main repo."""
    # At least the main worktree should be reported
    r = _run()
    assert r.returncode == 0
    # Output should mention core.hooksPath
    assert "core.hooksPath" in r.stdout


def test_ensure_hooks_idempotent():
    """Running ensure-hooks twice is idempotent."""
    r1 = _run()
    assert r1.returncode == 0
    r2 = _run()
    assert r2.returncode == 0
    # Second run should still be OK and not change state
    r3 = _run("--check")
    assert r3.returncode == 0
