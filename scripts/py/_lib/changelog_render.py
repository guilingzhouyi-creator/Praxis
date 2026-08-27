"""Changelog render library — scan/group/render the [Unreleased] block.

Scans git log subjects (from the most recent release tag, or all history) and
groups them by Conventional-Commits type into Keep-a-Changelog sections. Only
subjects that match the commit-msg type gate are recorded — a non-conventional
subject is silently dropped, so "detected type = update, else skip".

Library module — executed via the thin CLI wrapper:

    python scripts/py/gen_changelog.py            # update [Unreleased]
    python scripts/py/gen_changelog.py --dry-run  # preview, write nothing

Called before a release (or by `make changelog`); bump_version.py then moves
[Unreleased] into the versioned section.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"

# Commit-type whitelist comes from the SINGLE source of truth
# (config/discovery/commits.yaml) via _lib/commit_policy.py — never hardcode
# the type list here. The section mapping below is render-only.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from commit_policy import load_policy  # noqa: E402

_TYPES = load_policy().get("types", [])
_TYPE_SET = frozenset(_TYPES)

# Conventional-commit type -> Keep-a-Changelog section (Chinese, matching the
# existing CHANGELOG headers). Subjects not in the policy whitelist are
# dropped.
TYPE_TO_SECTION = {
    "feat": "新增",
    "fix": "修复",
    "perf": "性能",
    "refactor": "变更",
    "docs": "文档",
    "style": "变更",
    "test": "变更",
    "chore": "变更",
    "build": "变更",
    "ci": "变更",
}
_SUBJECT_RE = re.compile(r"^([a-z]+)(?:\(([^)]*)\))?!?:\s+(.+)$")
# Merge/revert subjects are not Conventional-Commits — skip them.
# `docs(changelog)` maintenance commits are also skipped: they refresh
# CHANGELOG.md itself, so counting them would make the freshness gate stale
# on every changelog-refresh commit (self-referential loop).
_SKIP_RE = re.compile(r"^(Merge|Revert)\b|^bump\b|^docs\(changelog\):")


def release_tag() -> str:
    """Most recent release tag (v*) reachable from HEAD, else the root range."""
    out = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], capture_output=True, text=True, cwd=ROOT)
    return out.stdout.strip() if out.stdout.strip() else ""


def scan_subjects() -> list[str]:
    """Subjects of commits after the last release tag (or all history)."""
    tag = release_tag()
    rng = f"{tag}..HEAD" if tag else "HEAD"
    out = subprocess.run(["git", "log", rng, "--pretty=%s", "--no-merges"], capture_output=True, text=True, cwd=ROOT)
    return [s.strip() for s in out.stdout.splitlines() if s.strip()]


def group_subjects(subjects: list[str]) -> dict[str, list[str]]:
    """Group conventional subjects by Keep-a-Changelog section (ordered).

    The type whitelist comes from config/discovery/commits.yaml (via
    commit_scan.load_policy) — a type removed there stops appearing in the
    changelog even if a section mapping still exists.
    """
    grouped: dict[str, list[str]] = {}
    for subj in subjects:
        if _SKIP_RE.match(subj):
            continue
        m = _SUBJECT_RE.match(subj)
        if not m:
            continue
        ctype = m.group(1)
        if ctype not in _TYPE_SET:
            continue  # type not in the policy whitelist — dropped
        section = TYPE_TO_SECTION.get(ctype)
        if section is None:
            continue
        summary = m.group(3).strip()
        scope = f" ({m.group(2)})" if m.group(2) else ""
        grouped.setdefault(section, []).append(f"- **{ctype.capitalize()}{scope}**: {summary}")
    return grouped


def render(grouped: dict[str, list[str]]) -> str:
    """Render the [Unreleased] block (empty if no type-detectable subjects)."""
    lines = ["## [Unreleased]", ""]
    if not grouped:
        lines += ["无类型化提交（feat/fix/perf/...）——本次无 changelog 条目。", ""]
        return "\n".join(lines)
    for section, items in grouped.items():
        lines.append(f"### {section}")
        lines.append("")
        lines.extend(items)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def update_changelog(block: str) -> None:
    """Replace the existing [Unreleased] block in CHANGELOG.md."""
    text = CHANGELOG.read_text(encoding="utf-8")
    pattern = re.compile(r"^## \[Unreleased\].*?(?=^## \[|\Z)", re.MULTILINE | re.DOTALL)
    new_text, n = pattern.subn(block + "\n", text)
    if n != 1:
        raise RuntimeError("expected exactly one [Unreleased] block in CHANGELOG.md")
    CHANGELOG.write_text(new_text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate [Unreleased] from git log")
    parser.add_argument("--dry-run", action="store_true", help="print the block, write nothing")
    args = parser.parse_args()

    grouped = group_subjects(scan_subjects())
    block = render(grouped)
    if args.dry_run:
        print(block)
        return 0
    update_changelog(block)
    print(f"CHANGELOG.md [Unreleased] updated ({len(grouped)} section(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
