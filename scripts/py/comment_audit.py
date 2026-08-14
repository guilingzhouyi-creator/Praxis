#!/usr/bin/env python3
"""Comment hygiene audit for the Praxis codebase.

Scans ``src/`` (or a path argument) for three comment-convention issues per
AGENTS.md: CJK residue in comments/docstrings, missing module/class/function
docstrings, and overly-short (low-detail) docstrings.

Exit codes:
  0  — PASS (no violations, or only tolerated ones)
  1  — violations found
  2  — usage / internal error

Usage:
  python scripts/py/comment_audit.py [path] [--strict]

``--strict`` turns all categories into hard failures (default: only CJK
residue and missing module docstrings fail; missing class/function docstrings
and short-docstring notes are advisory, because simple getters may skip per
AGENTS.md).
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
# Mojibake ranges (GBK-misdecoded UTF-8 box-drawing/em-dash residues).
MOJIBAKE_RE = re.compile(r"[\u9225\u922b\u923b\u9239]")
SHORT_DOC_MIN = 20
EXCLUDE_DIRS = {"locales", "skills"}
SKIP_FILES = {"injection.py"}


class AuditResult:
    """Collected violations grouped by category."""

    def __init__(self) -> None:
        self.cjk: list[str] = []
        self.mojibake: list[str] = []
        self.module: list[str] = []
        self.cls: list[str] = []
        self.func: list[str] = []
        self.short: list[str] = []

    @property
    def hard_errors(self) -> list[str]:
        return self.cjk + self.mojibake + self.module

    @property
    def advisory(self) -> list[str]:
        return self.cls + self.func + self.short

    def total(self) -> int:
        return len(self.hard_errors) + len(self.advisory)


def audit_file(path: str, rel: str, result: AuditResult) -> None:
    """Audit a single .py file into ``result``."""
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError):
        return

    # ── CJK / mojibake in comments ──
    for lineno, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            if CJK_RE.search(line):
                result.cjk.append(f"[CJK] {rel}:{lineno} {stripped[:70]}")
            if MOJIBAKE_RE.search(line):
                result.mojibake.append(f"[MOJIBAKE] {rel}:{lineno} {stripped[:70]}")

    # ── Module docstring ──
    has_mod_doc = bool(ast.get_docstring(tree))
    if not has_mod_doc:
        result.module.append(f"[MODULE] {rel} missing module docstring")

    # ── Class / function / docstring detail ──
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            doc = ast.get_docstring(node)
            if not doc:
                result.cls.append(f"[CLASS] {rel}:{node.lineno} {node.name} missing docstring")
            elif len(doc) < SHORT_DOC_MIN:
                result.short.append(f"[SHORT-CLASS] {rel}:{node.lineno} {node.name} {doc[:40]!r}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            doc = ast.get_docstring(node)
            if not doc:
                result.func.append(f"[FUNC] {rel}:{node.lineno} {node.name} missing docstring")
            elif len(doc) < SHORT_DOC_MIN:
                result.short.append(f"[SHORT-FUNC] {rel}:{node.lineno} {node.name} {doc[:40]!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="src", help="root to scan (default: src)")
    parser.add_argument("--strict", action="store_true", help="fail on advisory categories too")
    args = parser.parse_args()

    root = os.path.abspath(args.path)
    result = AuditResult()
    checked = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in sorted(files):
            if not fname.endswith(".py") or fname in SKIP_FILES:
                continue
            path = os.path.join(dirpath, fname)
            rel = os.path.relpath(path, os.path.dirname(root))
            if fname == "__init__.py":
                try:
                    with open(path, encoding="utf-8") as f:
                        if not f.read().strip():
                            continue
                except OSError:
                    continue
            audit_file(path, rel, result)
            checked += 1

    print(f"=== comment audit: {checked} files checked ===")
    for label, items in (
        ("CJK residue", result.cjk),
        ("mojibake", result.mojibake),
        ("missing module docstring", result.module),
        ("missing class docstring", result.cls),
        ("missing function docstring", result.func),
        ("short docstring (<{SHORT_DOC_MIN} chars)", result.short),
    ):
        print(f"{label}: {len(items)}")
        for item in items[:15]:
            print(f"  {item}")
        if len(items) > 15:
            print(f"  ... and {len(items) - 15} more")

    fail_count = len(result.hard_errors) if not args.strict else result.total()
    if fail_count:
        print(f"FAIL: {fail_count} hard issue(s) (strict={args.strict})")
        return 1
    print("PASS: no hard issues (advisory findings above, if any)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
