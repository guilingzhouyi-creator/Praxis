"""Classify a PR diff into code vs docs line counts for the auto-merge gate.

The auto-merge workflow uses this to decide whether a pull request is a
small, low-risk change (eligible for auto-merge) or a large code change
that must be held for review.  "Code" paths are implementation / build /
test / config files; "docs" are documentation trees and root-level
documentation files.  Unclassified paths are treated as code so a change
with unknown files can never slip through as "small".

Usage:
    python scripts/py/classify_diff.py --base <sha> --head <sha> [--threshold 1000]
    python scripts/py/classify_diff.py --numstat-file <path> [--threshold 1000]
    git diff --numstat base...head | python scripts/py/classify_diff.py [--threshold 1000]

Output (JSON):
    {"code_lines": int, "doc_lines": int, "total_lines": int,
     "is_large": bool, "threshold": int,
     "paths": {"code": [...], "docs": [...], "other": [...]}}
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

CODE_PREFIXES = ("src/", "tests/", "config/", "scripts/", ".github/", ".githooks/", "locales/", ".gitcode/")
CODE_FILES = {
    "pyproject.toml",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    ".pre-commit-config.yaml",
    ".gitleaks.toml",
    "codecov.yml",
    ".editorconfig",
    ".gitattributes",
    ".mcp.json",
}
DOC_PREFIXES = ("docs/",)
DOC_FILES = {"README.md", "AGENTS.md", "CHANGELOG.md", "LICENSE", ".praxis-rules.md"}


def classify(path: str) -> str:
    """Return "code", "docs", or "other" for a diff path."""
    if path.startswith(DOC_PREFIXES) or path in DOC_FILES:
        return "docs"
    if path.startswith(CODE_PREFIXES) or path in CODE_FILES:
        return "code"
    return "other"


def _parse_numstat(lines: list[str]) -> dict:
    """Aggregate numstat rows into code/docs line counts and path lists."""
    code_lines = 0
    doc_lines = 0
    code_paths: list[str] = []
    doc_paths: list[str] = []
    other_paths: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted = parts[0], parts[1]
        path = "\t".join(parts[2:])
        kind = classify(path)
        if added == "-" or deleted == "-":  # binary file
            delta = 0
        else:
            try:
                delta = int(added) + int(deleted)
            except ValueError:
                delta = 0
        if kind == "docs":
            doc_lines += delta
            doc_paths.append(path)
        else:
            code_lines += delta
            (code_paths if kind == "code" else other_paths).append(path)
    return {
        "code_lines": code_lines,
        "doc_lines": doc_lines,
        "code_paths": code_paths,
        "doc_paths": doc_paths,
        "other_paths": other_paths,
    }


def _git_numstat(base: str, head: str) -> list[str]:
    """Run ``git diff --numstat`` between two refs and return its lines."""
    proc = subprocess.run(
        ["git", "diff", "--numstat", f"{base}...{head}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            ["git", "diff", "--numstat", base, head],
            capture_output=True,
            text=True,
            check=False,
        )
    if proc.returncode != 0:
        sys.stderr.write(f"classify-diff: git diff failed: {proc.stderr}\n")
        sys.exit(1)
    return proc.stdout.splitlines()


def main() -> None:
    """CLI entry: read numstat from args/file/stdin and print JSON."""
    parser = argparse.ArgumentParser(description="Classify a diff into code vs docs lines.")
    parser.add_argument("--base", help="base ref (with --head, runs git diff --numstat)")
    parser.add_argument("--head", help="head ref (with --base)")
    parser.add_argument("--numstat-file", help="read numstat rows from a file instead of git")
    parser.add_argument("--threshold", type=int, default=1000, help="code-line threshold for 'large'")
    args = parser.parse_args()

    if args.base and args.head:
        rows = _git_numstat(args.base, args.head)
    elif args.numstat_file:
        with open(args.numstat_file, encoding="utf-8") as f:
            rows = f.read().splitlines()
    elif not sys.stdin.isatty():
        rows = sys.stdin.read().splitlines()
    else:
        parser.error("provide --base/--head, --numstat-file, or piped numstat on stdin")

    stats = _parse_numstat(rows)
    threshold = max(1, args.threshold)
    result = {
        "code_lines": stats["code_lines"],
        "doc_lines": stats["doc_lines"],
        "total_lines": stats["code_lines"] + stats["doc_lines"],
        "is_large": stats["code_lines"] >= threshold,
        "threshold": threshold,
        "paths": {
            "code": stats["code_paths"],
            "docs": stats["doc_paths"],
            "other": stats["other_paths"],
        },
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
