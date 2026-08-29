#!/usr/bin/env python3
"""
Document ingestion for pre-storage area.

- For files in docs/design/_incoming/*.md, automatically add 15-field English header,
  assign pointer/archive_number, generate abstract, determine fonds, and migrate
  to correct location (active or archive).
- For files already in docs/design/*.md, ensure header completeness.

Usage:
  python scripts/py/doc_ingest.py --file docs/design/_incoming/my-doc.md --apply
  python scripts/py/doc_ingest.py --staged --fix   # pre-commit: process staged incoming files
  python scripts/py/doc_ingest.py --staged --check # gate: validate only
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
INCOMING = ROOT / "docs/design/_incoming"
POINTERS_JSON = ROOT / "docs/design/POINTERS.json"
ARCHIVE = ROOT / "docs/design/archive"

# Fonds mapping
FONDS_MAP = {
    "DESIGN": {
        "code": "001",
        "retention": "permanent",
        "active_dir": ROOT / "docs/design",
        "archive_dir": ARCHIVE / "001-design" / "2026" / "permanent",
    },
    "REVIEW": {"code": "002", "retention": "longterm", "archive_dir": ARCHIVE / "002-review" / "2026" / "longterm"},
}


def load_pointers():
    if POINTERS_JSON.exists():
        return json.loads(POINTERS_JSON.read_text(encoding="utf-8"))
    return []


def next_seq_for_fonds(fonds, status="active"):
    pointers = load_pointers()
    # For active DESIGN, use 101-199; for archived DESIGN, 001-099; for REVIEW, 001-099
    if status == "active" and fonds == "DESIGN":
        # Find max active DESIGN seq
        max_seq = 100
        for p in pointers:
            if p.get("fonds") == "DESIGN" and p.get("status") == "active":
                m = re.search(r"-(\d+)$", p.get("archive_number", ""))
                if m:
                    try:
                        seq = int(m.group(1))
                        max_seq = max(max_seq, seq)
                    except Exception:
                        pass
        return max_seq + 1
    # For archived, find max in that fonds
    max_seq = 0
    for p in pointers:
        if p.get("fonds") == fonds and p.get("status") == "archived":
            m = re.search(r"-(\d+)$", p.get("archive_number", ""))
            if m:
                try:
                    seq = int(m.group(1))
                    max_seq = max(max_seq, seq)
                except Exception:
                    pass
    return max_seq + 1


def generate_abstract(text, title):
    parts = text.split("---", 2)
    body = parts[2] if len(parts) > 2 else text
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(">") or line.startswith("|") or line.startswith("```"):
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        if len(line) > 20:
            return line[:120]
    return f"Document on {title[:60]}"


def add_header_to_file(path: pathlib.Path, fonds="DESIGN", status="active"):
    text = path.read_text(encoding="utf-8", errors="ignore")
    # Check if already has header
    has_header = text.startswith("---")
    title = ""
    if has_header:
        m = re.search(r'^title:\s*"?([^"\n]+)"?', text, re.M)
        if m:
            title = m.group(1).strip()
    if not title:
        m = re.search(r"^#\s+(.+)$", text, re.M)
        title = m.group(1).strip() if m else path.stem

    # Generate pointer and archive_number
    seq = next_seq_for_fonds(fonds, status)
    year = "2026"
    retention = FONDS_MAP[fonds]["retention"] if fonds in FONDS_MAP else "permanent"
    if status == "active":
        pointer = f"DESIGN-{year}-08-29-{seq:03d}" if fonds == "DESIGN" else f"{fonds}-{year}-08-29-{seq:03d}"
        archive_number = f"{fonds}-{year}-{retention}-{seq:03d}"
    else:
        pointer = f"ARCH-{fonds}-{year}-08-29-{seq:03d}"
        archive_number = f"{fonds}-{year}-{retention}-{seq:03d}"

    abstract = generate_abstract(text, title)
    # Ensure abstract != title
    if abstract == title:
        abstract = f"Summary: {title} - detailed design"

    # Build new header
    header = f"""---
pointer: {pointer}
archive_number: {archive_number}
fonds: {fonds}
year: {year}
retention: {retention}
title: "{title[:80]}"
author: L3
formation_date: {year}-08-29
carrier: md
classification: internal
pages: {len(text.splitlines())}
archivist: L3
reviewer: L3
archive_date: {year}-08-29
source: {fonds.lower()}
keywords: []
abstract: "{abstract[:120]}"
---

"""
    if has_header:
        # Replace existing header
        end = text.find("\n---", 3)
        if end != -1:
            rest = text[end + 4 :].lstrip()
            new_text = header + rest
        else:
            new_text = header + text
    else:
        new_text = header + text

    path.write_text(new_text, encoding="utf-8")
    return pointer, archive_number


def process_incoming_file(path: pathlib.Path, apply=False):
    # Determine fonds from content or filename
    text = path.read_text(encoding="utf-8", errors="ignore")
    # Simple heuristic: if title contains review/audit, fonds=REVIEW, else DESIGN
    fonds = "DESIGN"
    if re.search(r"review|audit|评审", text, re.I):
        fonds = "REVIEW"
    status = "active"
    # If file is marked as archived in frontmatter, check status
    if "status: archived" in text:
        status = "archived"

    if apply:
        pointer, archive_number = add_header_to_file(path, fonds, status)
        # Determine target location
        if status == "active" and fonds == "DESIGN":
            target_dir = FONDS_MAP["DESIGN"]["active_dir"]
            # Ensure kebab name
            kebab = re.sub(r"[^a-z0-9-]", "-", path.stem.lower())
            kebab = re.sub(r"-+", "-", kebab).strip("-")
            target = target_dir / f"{kebab}.md"
            # Avoid collision
            if target.exists() and target != path:
                target = target_dir / f"{kebab}-{pointer.split('-')[-1]}.md"
            if target != path:
                path.rename(target)
                print(f"Moved {path.name} -> {target.relative_to(ROOT)}")
                return str(target.relative_to(ROOT)), None
            return str(target.relative_to(ROOT)), None
        # Archived: move to archive/001-design or 002-review
        info = FONDS_MAP.get(fonds, FONDS_MAP["DESIGN"])
        target_dir = info["archive_dir"]
        target_dir.mkdir(parents=True, exist_ok=True)
        kebab = re.sub(r"[^a-z0-9-]", "-", path.stem.lower())
        kebab = re.sub(r"-+", "-", kebab).strip("-")
        target = target_dir / f"{archive_number}_{kebab}.md"
        path.rename(target)
        print(f"Moved {path.name} -> {target.relative_to(ROOT)}")
        return str(target.relative_to(ROOT)), None
    # Check only
    if not text.startswith("---"):
        return None, "missing header"
    return None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="single file to process")
    parser.add_argument("--staged", action="store_true", help="process staged files in incoming")
    parser.add_argument("--fix", action="store_true", help="apply fixes")
    parser.add_argument("--check", action="store_true", help="check only")
    args = parser.parse_args()

    if args.file:
        p = pathlib.Path(args.file)
        if not p.exists():
            p = ROOT / args.file
        result, err = process_incoming_file(p, apply=args.fix)
        if err:
            print(f"Error: {err}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    if args.staged:
        # Find staged files in incoming
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=AM"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        staged = [line.strip() for line in out.stdout.splitlines() if line.strip()]
        incoming = [f for f in staged if "_incoming/" in f]
        if not incoming:
            # Also check for any docs/design/*.md that are staged and missing header (for direct writes)
            all_staged = [
                f
                for f in staged
                if f.startswith("docs/design/") and f.endswith(".md") and "_incoming" not in f and "archive" not in f
            ]
            # For check mode, we will validate them; for fix mode, we will add header
            if args.check:
                for f in all_staged:
                    p = ROOT / f
                    if p.exists():
                        txt = p.read_text(encoding="utf-8", errors="ignore")
                        if not txt.startswith("---") or "pointer:" not in txt:
                            print(
                                f"Gate blocked: {f} missing header (pointer/archive_number). Put it in _incoming/ or run doc_ingest.py --fix",
                                file=sys.stderr,
                            )
                            sys.exit(1)
            sys.exit(0)

        print(f"Found {len(incoming)} staged incoming files")
        for f in incoming:
            p = ROOT / f
            if not p.exists():
                continue
            if args.fix:
                result, err = process_incoming_file(p, apply=True)
                if err:
                    print(f"Blocked {f}: {err}", file=sys.stderr)
                    sys.exit(1)
                # After move, need to update git index: remove old, add new
                subprocess.run(["git", "rm", "--cached", f], cwd=str(ROOT))
                if result:
                    subprocess.run(["git", "add", result], cwd=str(ROOT))
                print(f"Auto-migrated {f} -> {result}")
            else:
                # Check
                txt = p.read_text(encoding="utf-8", errors="ignore")
                if not txt.startswith("---"):
                    print(f"Gate blocked: {f} missing header", file=sys.stderr)
                    sys.exit(1)
        # After fix, also regenerate POINTERS if needed
        if args.fix and incoming:
            print("Regenerating POINTERS...")
            subprocess.run([sys.executable, str(ROOT / "scripts/py/generate_pointers.py")], cwd=str(ROOT))
            subprocess.run(["git", "add", str(POINTERS_JSON)], cwd=str(ROOT))
            db = ROOT / "docs/design/POINTERS.db"
            if db.exists():
                subprocess.run(["git", "add", "-f", str(db)], cwd=str(ROOT))


if __name__ == "__main__":
    main()
