"""CHANGELOG freshness gate — [Unreleased] must include the latest typed commits.

Reuses generate-changelog's scan/group/render (loaded by path) to compute the
expected [Unreleased] entries from git log, then verifies CHANGELOG.md's
[Unreleased] block contains every one of them. Like check-doc-stats vs README,
this makes "run `make changelog` before release" a machine gate instead of a
reminder.

    python scripts/py/check-changelog.py           # check only (CI gate)
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"

# generate-changelog.py has a hyphen in its filename — load it by path.
_spec = importlib.util.spec_from_file_location("generate_changelog", ROOT / "scripts" / "py" / "generate-changelog.py")
generate_changelog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate_changelog)

_UNRELEASED_RE = re.compile(r"^## \[Unreleased\](.*?)(?=^## \[|\Z)", re.MULTILINE | re.DOTALL)
_ENTRY_RE = re.compile(r"^\s*- ", re.MULTILINE)


def current_unreleased_entries() -> list[str]:
    """Entry bullets currently in the [Unreleased] block."""
    text = CHANGELOG.read_text(encoding="utf-8")
    m = _UNRELEASED_RE.search(text)
    body = m.group(1) if m else ""
    return [line.strip() for line in body.splitlines() if _ENTRY_RE.match(line)]


def expected_unreleased_entries() -> list[str]:
    """Entry bullets generate-changelog would produce from the current git log."""
    grouped = generate_changelog.group_subjects(generate_changelog.scan_subjects())
    block = generate_changelog.render(grouped)
    return [line.strip() for line in block.splitlines() if _ENTRY_RE.match(line)]


def check() -> list[str]:
    """Generated entries missing from the [Unreleased] block (empty = in sync)."""
    current = current_unreleased_entries()
    expected = expected_unreleased_entries()
    if not expected:
        return []  # no typed commits since release — nothing to require
    return [e for e in expected if e not in current]


def main() -> int:
    missing = check()
    if not missing:
        print("CHANGELOG [Unreleased] is in sync with the latest commits.")
        return 0
    print("DRIFT: CHANGELOG [Unreleased] missing generated entries:")
    for e in missing:
        print(f" - {e}")
    print("Run `make changelog` (scripts/py/generate-changelog.py) then commit.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
