"""Tests for scripts/sh/verify-local-merge.sh — the local feature-branch merge gate.

Verifies the gate's behaviors in scratch repos that mirror the real
scripts/sh + scripts/py layout (the gate resolves its delegated
verify-main-merge-gate.sh via the repo root):
- running on main itself is a no-op (INFO, exit 0) — the local-merge gate
  applies to feature branches only;
- a feature branch with a tiny net delta is rejected (exit 1) — the
  delegated gate enforces the >= 1000 net threshold;
- an unresolvable branch fails usage (exit 2);
- a missing delegated gate script fails tooling (exit 3).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "sh" / "verify-local-merge.sh"
GATE = ROOT / "scripts" / "sh" / "verify-main-merge-gate.sh"
CLASSIFY = ROOT / "scripts" / "py" / "classify_diff.py"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )


def _install_gates(repo: Path) -> None:
    """Mirror the real gate scripts into the scratch repo (local-merge resolves
    them relative to the repo root, like the real gate does)."""
    (repo / "scripts" / "sh").mkdir(parents=True, exist_ok=True)
    (repo / "scripts" / "py").mkdir(parents=True, exist_ok=True)
    shutil.copy2(GATE, repo / "scripts" / "sh" / "verify-main-merge-gate.sh")
    shutil.copy2(CLASSIFY, repo / "scripts" / "py" / "classify_diff.py")


@pytest.fixture()
def scratch(tmp_path: Path) -> Path:
    """A scratch git repo with one commit on main and a tiny feature branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@test.local")
    _git(repo, "config", "user.name", "Praxis Test")
    (repo / "file.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "chore: seed main")
    _git(repo, "switch", "-q", "-c", "feature/tiny")
    (repo / "file.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "feat: tiny change")
    _git(repo, "switch", "-q", "main")
    _install_gates(repo)
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=repo,
    )


def test_main_is_noop(scratch: Path) -> None:
    """Running the gate while on main is an explicit no-op (exit 0)."""
    res = _run(scratch)
    assert res.returncode == 0
    assert "is main itself" in res.stderr


def test_tiny_branch_rejected(scratch: Path) -> None:
    """A feature branch below the net-delta threshold is rejected (exit 1)."""
    _git(scratch, "switch", "-q", "feature/tiny")
    res = _run(scratch)
    assert res.returncode == 1
    assert "does NOT yet qualify" in res.stdout


def test_unresolvable_branch_fails(scratch: Path) -> None:
    """A branch that does not exist fails with the usage error (exit 2)."""
    res = _run(scratch, "no/such-branch")
    assert res.returncode == 2


def test_requires_gate_script(scratch: Path) -> None:
    """Missing delegated gate script fails tooling (exit 3)."""
    _git(scratch, "switch", "-q", "feature/tiny")
    (scratch / "scripts" / "sh" / "verify-main-merge-gate.sh").unlink()
    res = _run(scratch)
    assert res.returncode == 3
