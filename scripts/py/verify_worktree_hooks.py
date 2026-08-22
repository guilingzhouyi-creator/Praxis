"""Verify worktree hooks — standalone check for CI and local.

Checks that every worktree has strict hooks, used by `ensure-hooks.sh --check`
and the commit-lint workflow. Exit 0 when all worktrees are strict.

Usage:
  python scripts/py/verify_worktree_hooks.py
  python scripts/py/verify_worktree_hooks.py --check
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOOKS = ["commit-msg", "pre-commit", "post-checkout"]


def _worktrees() -> list[Path]:
    """Return all worktree paths."""
    out = subprocess.run(["git", "worktree", "list", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout
    paths: list[Path] = []
    for line in out.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.split(" ", 1)[1]))
    return paths


def _check_hooks_path(wt: Path) -> list[str]:
    """Check core.hooksPath for a worktree, return violations."""
    r = subprocess.run(["git", "-C", str(wt), "config", "--get", "core.hooksPath"], capture_output=True, text=True)
    cur = r.stdout.strip()
    if cur != ".githooks":
        return [f"{wt}: core.hooksPath={cur!r}, expected '.githooks'"]
    return []


def _check_executable(wt: Path) -> list[str]:
    """Check executable bits, return violations."""
    violations: list[str] = []
    for name in HOOKS:
        p = wt / ".githooks" / name
        if p.exists() and not bool(p.stat().st_mode & 0o111):
            violations.append(f"{wt}: .githooks/{name} not executable")
        # Also check git index mode
        r = subprocess.run(
            ["git", "-C", str(wt), "ls-files", "--stage", f".githooks/{name}"], capture_output=True, text=True
        )
        if r.stdout and "100755" not in r.stdout and (wt / ".githooks" / name).exists():
            violations.append(f"{wt}: .githooks/{name} index not 100755")
    return violations


def _check_template(wt: Path) -> list[str]:
    """Check commit.template, return violations."""
    tmpl = wt / ".githooks" / "commit-template.txt"
    if not tmpl.exists():
        return []
    r = subprocess.run(["git", "-C", str(wt), "config", "--get", "commit.template"], capture_output=True, text=True)
    cur = r.stdout.strip()
    if cur != ".githooks/commit-template.txt":
        return [f"{wt}: commit.template={cur!r}, expected '.githooks/commit-template.txt'"]
    return []


def main() -> int:
    """CLI entry."""
    violations: list[str] = []
    for wt in _worktrees():
        violations.extend(_check_hooks_path(wt))
        violations.extend(_check_executable(wt))
        violations.extend(_check_template(wt))
        # Content check: commit-msg must contain the strict bypass audit
        p = wt / ".githooks" / "commit-msg"
        if p.exists():
            txt = p.read_text(encoding="utf-8")
            if "PRAXIS_SKIP_REASON" not in txt:
                violations.append(f"{wt}: .githooks/commit-msg missing strict bypass audit")
    if violations:
        print("[verify-worktree-hooks] VIOLATIONS:", file=sys.stderr)
        for v in violations:
            print(f"  ✗ {v}", file=sys.stderr)
        return 1
    print("[verify-worktree-hooks] OK — all worktrees strict")
    return 0


if __name__ == "__main__":
    sys.exit(main())
