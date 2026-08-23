"""Check commit template — validates .githooks/commit-template.txt.

Ensures the template documents all strict fields and is referenced by
git config commit.template. Used by ensure-hooks.sh --check and CI.

Usage:
  python scripts/py/commit_template_check.py
  python scripts/py/commit_template_check.py --check
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE = ROOT / ".githooks" / "commit-template.txt"


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
    import subprocess

    r = subprocess.run(["git", "config", "--get", "commit.template"], capture_output=True, text=True, cwd=ROOT)
    cur = r.stdout.strip()
    if cur != ".githooks/commit-template.txt":
        return [f"commit.template={cur!r}, expected '.githooks/commit-template.txt'"]
    return []


def main() -> int:
    """CLI entry."""
    import argparse

    parser = argparse.ArgumentParser(description="Check commit template")
    parser.add_argument("--check", action="store_true", help="check only, no fix")
    parser.parse_args()

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


if __name__ == "__main__":
    sys.exit(main())
