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

# CJK residue — now covering the FULL CJK plane (unified ideographs +
# kana + hangul + fullwidth forms + extension B), so 0-CJK truly means
# no East-Asian writing-system residue in comments/docs.
CJK_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"  # unified + ext A + compat
    r"\u3040-\u30ff"  # hiragana / katakana
    r"\u3000-\u303f"  # CJK punctuation + ideographic space
    r"\uac00-\ud7af"  # hangul syllables
    r"\uff00-\uffef"  # fullwidth forms
    r"\U00020000-\U0002a6df"  # ext B
    r"]"
)
# Mojibake ranges (GBK-misdecoded UTF-8 box-drawing/em-dash residues).
MOJIBAKE_RE = re.compile(r"[\u9225\u922b\u923b\u9239]")
# Legal non-ASCII characters frequently used in English comments/docs
# (surveyed across the tree: box-drawing separators, arrows, section sign,
# math symbols, circled ordinals, ellipsis). Whitelisted so the strict
# non-ASCII scan never false-positives on intentional typography.
ALLOWED_NON_ASCII = frozenset(
    "\u2014\u2013\u2192\u2190\u2194\u2191\u2193\u2198\u21c4"  # — – → ← ↔ ↑ ↓ ↘ ⇄
    "\u25ba\u25b6\u25bc"  # ► ▶ ▼ (flow/pointer glyphs)
    "\u00d7\u00f7\u00b1\u2265\u2264\u00a7\u2026"  # × ÷ ± ≥ ≤ § …
    "\u2500\u2550\u251c\u2514\u2502\u250c\u2534\u2510\u252c\u2518"  # box-drawing ─ ═ ├ └ │ ┌ ┴ ┐ ┬ ┘
    "\u27e8\u27e9"  # ⟨ ⟩ (math/type brackets)
    "\u2022\u00b7"  # • · (bullets/separators)
    "\u03a9"  # Ω (units in prose)
    "\u00e7"  # ç (borrowed words: façade)
    "\u2460\u2461\u2462\u2463\u2464\u2465"  # ① ② ③ ④ ⑤ ⑥
    "\U0001f195"  # 🆕 (NEW marker in ASCII-art diagrams)
)
SHORT_DOC_MIN = 20
EXCLUDE_DIRS = {"locales", "skills"}
SKIP_FILES = {"injection.py"}


class AuditResult:
    """Collected violations grouped by category."""

    def __init__(self) -> None:
        self.cjk: list[str] = []
        self.mojibake: list[str] = []
        self.non_ascii: list[str] = []
        self.module: list[str] = []
        self.cls: list[str] = []
        self.func: list[str] = []
        self.short: list[str] = []

    @property
    def hard_errors(self) -> list[str]:
        return self.cjk + self.mojibake + self.non_ascii + self.module

    @property
    def advisory(self) -> list[str]:
        return self.cls + self.func + self.short

    def total(self) -> int:
        return len(self.hard_errors) + len(self.advisory)


def _non_ascii_residue(line: str) -> str:
    """Non-ASCII characters in a line, minus the typography whitelist."""
    return "".join(ch for ch in line if ord(ch) > 127 and ch not in ALLOWED_NON_ASCII)


def audit_file(path: str, rel: str, result: AuditResult, strict: bool = False) -> None:
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
            if strict:
                residue = _non_ascii_residue(line)
                if residue:
                    result.non_ascii.append(f"[NON-ASCII] {rel}:{lineno} {residue[:12]!r} in {stripped[:50]}")

    # ── Module docstring ──
    mod_doc = ast.get_docstring(tree)
    if not mod_doc:
        result.module.append(f"[MODULE] {rel} missing module docstring")
    else:
        _scan_docstring(mod_doc, rel, "<module>", result, strict)

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
            _scan_docstring(doc, rel, node.name, result, strict)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            doc = ast.get_docstring(node)
            if not doc:
                result.func.append(f"[FUNC] {rel}:{node.lineno} {node.name} missing docstring")
            elif len(doc) < SHORT_DOC_MIN:
                result.short.append(f"[SHORT-FUNC] {rel}:{node.lineno} {node.name} {doc[:40]!r}")
            _scan_docstring(doc, rel, node.name, result, strict)


def _scan_docstring(doc: str, rel: str, name: str, result: AuditResult, strict: bool) -> None:
    """Scan a docstring body for CJK/mojibake/non-ASCII residue (strict 2)."""
    if not doc:
        return
    if CJK_RE.search(doc):
        result.cjk.append(f"[CJK-DOC] {rel} {name} docstring: {doc[:40]!r}")
    if MOJIBAKE_RE.search(doc):
        result.mojibake.append(f"[MOJIBAKE-DOC] {rel} {name} docstring")
    if strict:
        residue = _non_ascii_residue(doc)
        if residue:
            result.non_ascii.append(f"[NON-ASCII-DOC] {rel} {name} docstring {residue[:12]!r}")


def audit_md_file(path: str, rel: str, result: AuditResult, strict: bool = False) -> None:
    """Audit a Markdown file for CJK/mojibake/non-ASCII residue (strict 3).

    Markdown has no AST — every line is scanned for residue; the same
    CJK/mojibake rules apply, plus the strict non-ASCII whitelist scan.
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return
    for lineno, line in enumerate(lines, 1):
        if CJK_RE.search(line):
            result.cjk.append(f"[CJK-MD] {rel}:{lineno} {line.strip()[:70]}")
        if MOJIBAKE_RE.search(line):
            result.mojibake.append(f"[MOJIBAKE-MD] {rel}:{lineno}")
        if strict:
            residue = _non_ascii_residue(line)
            if residue:
                result.non_ascii.append(f"[NON-ASCII-MD] {rel}:{lineno} {residue[:12]!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="src", help="root to scan (default: src)")
    parser.add_argument("--strict", action="store_true", help="fail on advisory categories too")
    parser.add_argument(
        "--non-ascii",
        action="store_true",
        help="also flag non-ASCII residue (strict-1/2 scan) without failing advisory categories",
    )
    args = parser.parse_args()

    root = os.path.abspath(args.path)
    result = AuditResult()
    checked = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in sorted(files):
            if fname.endswith(".py"):
                if fname in SKIP_FILES:
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
                audit_file(path, rel, result, strict=args.strict or args.non_ascii)
                checked += 1
            elif fname.endswith(".md"):
                # Strict 3: Markdown docs carry the same English-baseline
                # gate (no AST — line scan).
                path = os.path.join(dirpath, fname)
                rel = os.path.relpath(path, os.path.dirname(root))
                audit_md_file(path, rel, result, strict=args.strict or args.non_ascii)
                checked += 1

    print(f"=== comment audit: {checked} files checked ===")
    for label, items in (
        ("CJK residue", result.cjk),
        ("mojibake", result.mojibake),
        ("non-ASCII residue (strict)", result.non_ascii),
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
