#!/usr/bin/env python3
"""
Doc gate for pre-commit: validates staged docs and blocks on violations.

- Checks all staged docs/design/*.md (excluding _incoming, archive, README, archive-spec)
  for required English header DSL, duplicate pointer/archive_number, and folder correctness.
- If staged files are in _incoming/, it auto-fixes them via doc_ingest.py --fix (when called with --fix).
- Exit 1 blocks commit and prints Agent-friendly message.

Usage in pre-commit:
  python scripts/py/check_doc_gate.py --staged --fix   # auto-migrate incoming and validate
  python scripts/py/check_doc_gate.py --staged --check # validate only
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
POINTERS_JSON = ROOT / "docs/design/POINTERS.json"

REQUIRED_FIELDS = [
    "pointer",
    "archive_number",
    "fonds",
    "year",
    "retention",
    "title",
    "author",
    "formation_date",
    "carrier",
    "classification",
    "pages",
    "archivist",
    "reviewer",
    "archive_date",
    "source",
    "keywords",
    "abstract",
    "construction",
]


def staged_files():
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=AM"], capture_output=True, text=True, cwd=str(ROOT)
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def validate_file(path: pathlib.Path):
    errors = []
    if not path.exists():
        return [f"file not found: {path}"]
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---"):
        errors.append(f"{path}: missing frontmatter header (---)")
        return errors
    # Check required fields
    for field in REQUIRED_FIELDS:
        if not re.search(rf"^{field}:\s*.+", text, re.M):
            errors.append(f"{path}: missing required field '{field}:' (English header DSL required)")
    # Check pointer format
    m = re.search(r"^pointer:\s*(\S+)", text, re.M)
    if m:
        pointer = m.group(1)
        if not re.match(r"^(DESIGN|ARCH-DESIGN|ARCH-REVIEW|ROADMAP|ARCH-ROADMAP)-", pointer):
            errors.append(
                f"{path}: invalid pointer '{pointer}' (must start with DESIGN/ARCH-DESIGN/ARCH-REVIEW/ROADMAP/ARCH-ROADMAP)"
            )
    # Check construction status vocabulary (real-world implementation state;
    # orthogonal to library lifecycle `status`). Blocked on unknown values so
    # body/header drift (planned-but-implemented) cannot pass silently.
    m = re.search(r"^construction:\s*(\S+)", text, re.M)
    if m:
        construction = m.group(1)
        if construction not in ("planned", "in_progress", "closed"):
            errors.append(f"{path}: invalid construction '{construction}' (must be planned|in_progress|closed)")
    # Check kebab filename
    if path.parent.name != "_incoming" and "archive" not in str(path) and not re.match(r"^[a-z0-9-]+\.md$", path.name):
        errors.append(f"{path.name}: must be kebab-case (lowercase, hyphens, no praxis- prefix)")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    files = staged_files()
    # Filter to docs/design + docs/roadmaps (two independent fonds, same gate)
    design_files = [
        f
        for f in files
        if (f.startswith("docs/design/") or f.startswith("docs/roadmaps/"))
        and f.endswith(".md")
        and "archive" not in f
        and "_incoming" not in f
        and "_outgoing" not in f
        and not f.endswith("README.md")
        and not f.endswith("archive-spec.md")
    ]
    incoming_files = [
        f
        for f in files
        if "_incoming/" in f and f.endswith(".md") and not f.endswith("README.md") and not f.endswith(".gitkeep")
    ]

    # If incoming files staged and --fix, auto-process them
    if incoming_files and args.fix:
        print(f"--- doc gate: processing {len(incoming_files)} incoming files ---")
        for f in incoming_files:
            # Call doc_ingest for each
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/py/doc_ingest.py"), "--file", f, "--fix"],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            if result.returncode != 0:
                print(f"Failed to ingest {f}: {result.stderr}", file=sys.stderr)
            else:
                if result.stdout:
                    print(result.stdout.strip())
                if result.stderr:
                    print(result.stderr.strip(), file=sys.stderr)
        # After processing, regenerate pointers
        subprocess.run([sys.executable, str(ROOT / "scripts/py/generate_pointers.py")], cwd=str(ROOT))
        subprocess.run(["git", "add", str(POINTERS_JSON)], cwd=str(ROOT))
        db = ROOT / "docs/design/POINTERS.db"
        if db.exists():
            subprocess.run(["git", "add", "-f", str(db)], cwd=str(ROOT))

    # Outgoing pre-storage: completed docs (construction: closed) staged in
    # _outgoing/ are auto-archived on commit — the seamless "roadmap completes
    # -> archived" bridge (mirror of _incoming ingestion, out direction).
    outgoing_files = [f for f in files if "_outgoing/" in f and f.endswith(".md") and not f.endswith("README.md")]
    if outgoing_files and args.fix:
        print(f"--- doc gate: archiving {len(outgoing_files)} outgoing file(s) ---")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/py/doc_archive.py"), "--staged", "--fix"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            print(result.stdout, file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)
        if result.stdout:
            print(result.stdout.strip())

    # Validate all staged design files (including those just fixed, re-read staged list)
    files = staged_files()
    design_files = [
        f
        for f in files
        if (f.startswith("docs/design/") or f.startswith("docs/roadmaps/"))
        and f.endswith(".md")
        and "archive" not in f
        and "_incoming" not in f
        and "_outgoing" not in f
        and not f.endswith("README.md")
        and not f.endswith("archive-spec.md")
    ]

    all_errors = []
    seen_pointers = {}
    seen_archive_numbers = {}
    for f in design_files:
        p = ROOT / f
        errs = validate_file(p)
        all_errors.extend(errs)
        # Check duplicates
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="ignore")
            m_ptr = re.search(r"^pointer:\s*(\S+)", text, re.M)
            m_arch = re.search(r"^archive_number:\s*(\S+)", text, re.M)
            if m_ptr:
                ptr = m_ptr.group(1)
                if ptr in seen_pointers:
                    all_errors.append(f"{f}: duplicate pointer '{ptr}' also in {seen_pointers[ptr]}")
                else:
                    seen_pointers[ptr] = f
            if m_arch:
                arch = m_arch.group(1)
                if arch in seen_archive_numbers:
                    all_errors.append(f"{f}: duplicate archive_number '{arch}' also in {seen_archive_numbers[arch]}")
                else:
                    seen_archive_numbers[arch] = f

    # Also check POINTERS.json for duplicates across entire archive
    if POINTERS_JSON.exists():
        try:
            data = json.loads(POINTERS_JSON.read_text(encoding="utf-8"))
            c_ptr = {}
            c_arch = {}
            for e in data:
                ptr = e.get("pointer")
                arch = e.get("archive_number")
                if ptr in c_ptr:
                    all_errors.append(f"POINTERS.json: duplicate pointer '{ptr}'")
                c_ptr[ptr] = 1
                if arch in c_arch:
                    all_errors.append(f"POINTERS.json: duplicate archive_number '{arch}'")
                c_arch[arch] = 1
        except Exception:
            pass

    if all_errors:
        print("\n--- DOC GATE BLOCKED ---", file=sys.stderr)
        for err in all_errors:
            print(f"  ✗ {err}", file=sys.stderr)
        print("\nFix:", file=sys.stderr)
        print(
            "  - Put new docs in docs/design/_incoming/*.md (kebab-case) and commit; the gate will auto-tag and migrate",
            file=sys.stderr,
        )
        print("  - Or run: python scripts/py/doc_ingest.py --file <path> --fix", file=sys.stderr)
        print("  - Ensure the English header DSL (pointer/archive_number/fonds/...) is present", file=sys.stderr)
        print("  - Check POINTERS.json for duplicate pointer/archive_number", file=sys.stderr)
        sys.exit(1)
    else:
        if design_files or incoming_files:
            print(f"--- doc gate: OK ({len(design_files)} active, {len(incoming_files)} incoming) ---")
        sys.exit(0)


if __name__ == "__main__":
    main()
