"""Commit governance gate — single CLI over the commit-policy surface.

Folds the former ``commit_strict.py`` and ``commit_template_check.py`` CLIs;
the policy engine itself lives in ``_lib/commit_policy.py`` and is exposed
here as the ``policy`` subcommand with its original flag interface intact:

    python scripts/py/commit_gate.py policy --subject "feat(l1): add x"
    python scripts/py/commit_gate.py policy --msg "$(git log -1 --format=%B)"
    python scripts/py/commit_gate.py --msg "feat(l3): add x\\n\\n..."     # lint
    python scripts/py/commit_gate.py --range main..HEAD
    python scripts/py/commit_gate.py --worktree-check
    python scripts/py/commit_gate.py template --check
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "py" / "_lib"))
TEMPLATE = ROOT / ".githooks" / "commit-template.txt"

_SELF = Path(__file__).resolve()


# ── policy engine delegation ────────────────────────────────────────────
def _policy_main(rest: list[str]) -> int:
    """Run the policy engine's main() with argv patched for its parser."""
    import commit_policy  # loaded from _lib via sys.path insert above

    old_argv = sys.argv
    try:
        sys.argv = ["commit-gate policy", *rest]
        return int(commit_policy.main())
    finally:
        sys.argv = old_argv


# ── strict lint (former commit_strict.py) ──────────────────────────────
def _run_policy_cli(args: list[str]) -> tuple[int, str, str]:
    """Run this file in policy mode, returning (rc, stdout, stderr)."""
    proc = subprocess.run([sys.executable, str(_SELF), "policy", *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def lint_msg(msg: str, branch: str = "") -> bool:
    """Lint a single commit message, return True if it passes."""
    rc, _, _ = _run_policy_cli(["--msg", msg, "--branch", branch])
    return rc == 0


def lint_range(rev_range: str, branch: str = "") -> bool:
    """Lint a git range, return True if all commits pass."""
    rc, _, _ = _run_policy_cli(["--git-range", rev_range, "--branch", branch])
    return rc == 0


def worktree_check() -> bool:
    """Check that all worktrees have strict hooks (delegates to ensure-hooks.sh)."""
    script = ROOT / "scripts" / "sh" / "ensure-hooks.sh"
    proc = subprocess.run(["bash", str(script), "--check"], capture_output=True, text=True)
    return proc.returncode == 0


def _lint_main() -> int:
    """Former commit_strict.py CLI entry, flag-for-flag."""
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


# ── template check (former commit_template_check.py) ───────────────────
def check_template() -> list[str]:
    """Validate the commit template, return violations."""
    violations: list[str] = []
    if not TEMPLATE.exists():
        return [f"{TEMPLATE} missing"]
    text = TEMPLATE.read_text(encoding="utf-8")
    if "type(scope):" not in text:
        violations.append("template missing 'type(scope):' example")
    if "Co-Authored-By" not in text:
        violations.append("template missing 'Co-Authored-By' trailer")
    if "72" not in text:
        violations.append("template missing '72' length hint")
    if "English" not in text:
        violations.append("template missing 'English' requirement")
    # Blank line before the trailer example — accepts both the raw form
    # (``\n\nCo-Authored-By``, which git would prefill into new commits)
    # and the commented presentation (``#\n# Co-Authored-By``) that keeps
    # the template from prefilling an attribution line.
    if "\n\nCo-Authored-By" not in text and "\n#\n# Co-Authored-By" not in text:
        violations.append("template should show blank line before Co-Authored-By")
    return violations


def check_config() -> list[str]:
    """Check git config commit.template, return violations."""
    r = subprocess.run(["git", "config", "--get", "commit.template"], capture_output=True, text=True, cwd=ROOT)
    cur = r.stdout.strip()
    if cur != ".githooks/commit-template.txt":
        return [f"commit.template={cur!r}, expected '.githooks/commit-template.txt'"]
    return []


def _template_main() -> int:
    """Former commit_template_check.py CLI entry, output-identical."""
    violations: list[str] = []
    violations.extend(check_template())
    violations.extend(check_config())

    if violations:
        print("[commit-template-check] VIOLATIONS:", file=sys.stderr)
        for v in violations:
            print(f"  ✗ {v}", file=sys.stderr)
        return 1
    print("[commit-template-check] OK — template strict and configured")
    return 0


def main() -> int:
    """CLI entry — routes policy / template / default-lint."""
    argv = sys.argv[1:]
    if argv and argv[0] == "policy":
        return _policy_main(argv[1:])
    if argv and argv[0] == "template":
        return _template_main()
    # Bare flags (or none) fall through to the strict lint parser.
    return _lint_main()


if __name__ == "__main__":
    sys.exit(main())
