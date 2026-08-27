"""CHANGELOG freshness gate — [Unreleased] must include the latest typed commits.

Reuses changelog_render's scan/group/render (loaded from ``_lib``) to compute
the expected [Unreleased] entries from git log, then verifies CHANGELOG.md's
[Unreleased] block contains every one of them. Like check-doc-stats vs README,
this makes "run `make changelog` before release" a machine gate instead of a
reminder.

    python scripts/py/check_changelog.py           # check only (CI gate)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"

sys.path.insert(0, str(ROOT / "scripts" / "py" / "_lib"))
import changelog_render  # noqa: E402

_UNRELEASED_RE = re.compile(r"^## \[Unreleased\](.*?)(?=^## \[|\Z)", re.MULTILINE | re.DOTALL)
_ENTRY_RE = re.compile(r"^\s*- ", re.MULTILINE)


def current_unreleased_entries() -> list[str]:
    """Entry bullets currently in the [Unreleased] block."""
    text = CHANGELOG.read_text(encoding="utf-8")
    m = _UNRELEASED_RE.search(text)
    body = m.group(1) if m else ""
    return [line.strip() for line in body.splitlines() if _ENTRY_RE.match(line)]


def expected_unreleased_entries() -> list[str]:
    """Entry bullets gen-changelog would produce from the current git log."""
    grouped = changelog_render.group_subjects(changelog_render.scan_subjects())
    block = changelog_render.render(grouped)
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
    print("Run `make changelog` (scripts/py/gen_changelog.py) then commit.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
