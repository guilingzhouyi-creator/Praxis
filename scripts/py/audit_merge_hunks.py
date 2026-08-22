#!/usr/bin/env python3
"""Audit sensitive merge paths at unified-diff hunk granularity.

The roadmap and discovery registries are stateful documents/configuration, so
an old branch snapshot must never replace them silently. This report lists
every hunk under the protected prefixes and rejects a one-hunk replacement of
an entire existing file when ``--check`` is requested. Normal multi-hunk edits
remain valid, but their hunk inventory is explicit for human review.

Usage::

    python scripts/py/audit_merge_hunks.py --base main --head feature/x --check
    python scripts/py/audit_merge_hunks.py --base main --head feature/x --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SENSITIVE_PREFIXES = ("docs/roadmaps/", "config/discovery/")
_HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)
_DIFF_PATH_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")


@dataclass
class HunkAudit:
    """One unified-diff hunk and its added/deleted line counts."""

    header: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    additions: int = 0
    deletions: int = 0


@dataclass
class FileAudit:
    """Hunk inventory and replacement classification for one sensitive file."""

    path: str
    old_lines: int
    new_lines: int
    hunks: list[HunkAudit] = field(default_factory=list)
    whole_file_replacement: bool = False


def _run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _line_count(ref: str, path: str) -> int:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 0
    return len(result.stdout.splitlines())


def audit(base: str, head: str) -> list[FileAudit]:
    """Return sensitive-file hunk audits for ``base..head``."""

    diff = _run_git(
        "diff",
        "--no-ext-diff",
        "--no-renames",
        "--unified=0",
        base,
        head,
        "--",
        *SENSITIVE_PREFIXES,
    )
    audits: dict[str, FileAudit] = {}
    current: FileAudit | None = None
    hunk: HunkAudit | None = None
    for line in diff.splitlines():
        path_match = _DIFF_PATH_RE.match(line)
        if path_match and path_match.group(1) == path_match.group(2):
            path = path_match.group(1)
            current = FileAudit(path=path, old_lines=_line_count(base, path), new_lines=_line_count(head, path))
            audits[path] = current
            hunk = None
            continue
        if current is None:
            continue
        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            values = hunk_match.groupdict()
            hunk = HunkAudit(
                header=line,
                old_start=int(values["old_start"]),
                old_count=int(values["old_count"] or 1),
                new_start=int(values["new_start"]),
                new_count=int(values["new_count"] or 1),
            )
            current.hunks.append(hunk)
            continue
        if hunk is not None and line.startswith("+") and not line.startswith("+++"):
            hunk.additions += 1
        elif hunk is not None and line.startswith("-") and not line.startswith("---"):
            hunk.deletions += 1

    for item in audits.values():
        if len(item.hunks) != 1 or item.old_lines <= 0 or item.new_lines <= 0:
            continue
        only = item.hunks[0]
        item.whole_file_replacement = (
            only.old_start == 1
            and only.old_count == item.old_lines
            and only.new_start == 1
            and only.new_count == item.new_lines
        )
    return list(audits.values())


def _report(audits: list[FileAudit]) -> dict[str, object]:
    return {
        "sensitive_prefixes": list(SENSITIVE_PREFIXES),
        "files": [asdict(item) for item in audits],
        "whole_file_replacements": [item.path for item in audits if item.whole_file_replacement],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="base ref for the merge review")
    parser.add_argument("--head", required=True, help="incoming branch or commit")
    parser.add_argument("--check", action="store_true", help="fail on whole-file replacement")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        audits = audit(args.base, args.head)
    except subprocess.CalledProcessError as error:
        print(error.stderr or str(error), file=sys.stderr)
        return 2

    report = _report(audits)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif not audits:
        print("[merge-hunks] no sensitive files changed")
    else:
        for item in audits:
            marker = " WHOLE_FILE_REPLACEMENT" if item.whole_file_replacement else ""
            print(f"[merge-hunks] {item.path}: {len(item.hunks)} hunk(s){marker}")
            for hunk in item.hunks:
                print(f"  {hunk.header} (+{hunk.additions}/-{hunk.deletions})")

    replacements = report["whole_file_replacements"]
    if args.check and replacements:
        print(
            "[merge-hunks] REJECTED: sensitive files contain whole-file replacements; "
            "review each hunk against both branch intents before merging:",
            file=sys.stderr,
        )
        for path in replacements:
            print(f"  - {path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
