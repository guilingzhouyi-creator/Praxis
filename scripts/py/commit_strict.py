"""Strict commit enforcer — worktree-aware wrapper over commit_scan.

CLI for local and CI to lint a single message or a git range with worktree
awareness. Used by ensure-hooks.sh --check and the commit-lint workflow.

Usage:
  python scripts/py/commit_strict.py --msg "feat(l3): add x ..."
  python scripts/py/commit_strict.py --range main..HEAD
  python scripts/py/commit_strict.py --worktree-check
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCAN = ROOT / "scripts" / "py" / "commit_scan.py"
DETECT = ROOT / "scripts" / "py" / "detect_agent.py"


def _run_scan(args: list[str]) -> tuple[int, str, str]:
    """Run commit_scan.py with args, return (rc, stdout, stderr)."""
    proc = subprocess.run([sys.executable, str(SCAN), *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def lint_msg(msg: str, branch: str = "") -> bool:
    """Lint a single commit message, return True if it passes."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write(msg)
        path = f.name
    try:
        rc, out, err = _run_scan(["--msg", msg, "--branch", branch])
        return rc == 0
    finally:
        Path(path).unlink(missing_ok=True)


def lint_range(rev_range: str, branch: str = "") -> bool:
    """Lint a git range, return True if all commits pass."""
    rc, _, _ = _run_scan(["--git-range", rev_range, "--branch", branch])
    return rc == 0


def worktree_check() -> bool:
    """Check that all worktrees have strict hooks (delegates to ensure-hooks.sh)."""
    script = ROOT / "scripts" / "sh" / "ensure-hooks.sh"
    proc = subprocess.run(["bash", str(script), "--check"], capture_output=True, text=True)
    return proc.returncode == 0


def main() -> int:
    """CLI entry."""
    parser = argparse.ArgumentParser(description="Strict commit enforcer (worktree-aware)")
    parser.add_argument("--msg", help="single commit message to lint")
    parser.add_argument("--range", help="git range like main..HEAD")
    parser.add_argument("--branch", default="", help="branch for branch-policy checks")
    parser.add_argument("--worktree-check", action="store_true", help="check worktree hooks inheritance")
    args = parser.parse_args()

    if args.worktree_check:
        ok = worktree_check()
        print("[commit-strict] worktree check: " + ("OK" if ok else "FAIL"))
        return 0 if ok else 1

    if args.msg:
        ok = lint_msg(args.msg, branch=args.branch)
        print("[commit-strict] msg: " + ("OK" if ok else "FAIL"))
        return 0 if ok else 1

    if args.range:
        ok = lint_range(args.range, branch=args.branch)
        print(f"[commit-strict] range {args.range}: " + ("OK" if ok else "FAIL"))
        return 0 if ok else 1

    parser.error("provide --msg, --range, or --worktree-check")
    return 2


if __name__ == "__main__":
    sys.exit(main())
