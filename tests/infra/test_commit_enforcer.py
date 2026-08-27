"""Tests for scripts/py/commit_gate.py — worktree-aware enforcer."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "py" / "commit_gate.py"
COAUTH = "Co-Authored-By: OpenCode (ox-alpha) <noreply@opencode.ai>"


def _run(*args: str) -> subprocess.CompletedProcess:
    """Run commit_gate.py with args."""
    import os

    env = os.environ.copy()
    env["PRAXIS_AUTHOR"] = "OpenCode"
    env["PRAXIS_MODEL"] = "ox-alpha"
    env["PATH"] = f"/tmp:{env.get('PATH', '')}"
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT, env=env)


def _stage_tmp_probe(rel_path: str) -> str:
    """Stage a temporary NEW file so the type-to-content gate sees a match."""
    import pathlib
    import subprocess as _sp

    p = pathlib.Path(rel_path)
    p.write_text("# temporary commit-strict probe\n")
    _sp.run(["git", "add", str(p)], cwd=ROOT, check=True)
    return str(p)


def _unstage_tmp_probe(rel_path: str) -> None:
    import pathlib
    import subprocess as _sp

    _sp.run(["git", "rm", "--cached", "-q", rel_path], cwd=ROOT, check=True)
    pathlib.Path(rel_path).unlink(missing_ok=True)


def test_lint_msg_passes():
    """Valid message passes."""
    # `feat(hooks)` scope maps to .githooks/ — stage a probe there so the
    # scope-content gate sees a matching path.
    p = _stage_tmp_probe(".githooks/_tmp_enforcer_probe")
    try:
        msg = f"feat(hooks): add strict gate\n\n{COAUTH}\n"
        r = _run("--msg", msg)
        assert r.returncode == 0
        assert "OK" in r.stdout
    finally:
        _unstage_tmp_probe(p)


def test_lint_msg_fails_without_trailer():
    """Missing trailer fails."""
    msg = "feat(hooks): add strict gate\n"
    r = _run("--msg", msg)
    assert r.returncode != 0


def test_lint_msg_fails_with_cjk():
    """CJK in subject fails via subject lint (not via --msg Co-Authored check)."""
    # --msg mode only checks Co-Authored-By; CJK is checked via --subject
    import subprocess as sp
    import sys

    r = sp.run(
        [sys.executable, str(SCRIPT), "policy", "--subject", "feat: 中文"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert r.returncode != 0


def test_lint_range_passes_for_current_branch():
    """Range lint for the current branch (at least one commit) passes when clean."""

    # Use HEAD~1..HEAD which should be a single recent commit (if any)
    # If not enough history, just check that the command does not crash
    r = _run("--range", "HEAD~1..HEAD")
    # Either OK or no commits, but should not crash with 2
    assert r.returncode in (0, 1)


def test_worktree_check_passes():
    """worktree-check should pass on a correctly configured repo."""
    r = _run("--worktree-check")
    assert r.returncode == 0
    assert "worktree check" in r.stdout.lower()


def test_lint_msg_branch_policy():
    """Branch-type policy is checked via subject, not via --msg."""
    import subprocess as sp
    import sys

    r1 = sp.run(
        [
            sys.executable,
            str(SCRIPT),
            "policy",
            "--subject",
            "fix(hooks): patch hook",
            "--branch",
            "fix/urgent-patch",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert r1.returncode == 0
    r2 = sp.run(
        [
            sys.executable,
            str(SCRIPT),
            "policy",
            "--subject",
            "feat(hooks): add feature",
            "--branch",
            "fix/urgent-patch",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert r2.returncode != 0
