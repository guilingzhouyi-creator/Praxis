#!/usr/bin/env python3
"""
Document archival from the pre-storage (outgoing) area.

Mirror of doc_ingest.py for the OUT direction: a completed doc
(`construction: closed`) placed in docs/design/_outgoing/ is auto-archived
on commit — frontmatter re-pointed (ARCH-* pointer, archive_number in the
fonds' permanent/long-term series, series: archive, status: archived, +
original_name), moved into the fonds' archive dir, the active copy removed,
and POINTERS regenerated. This is the seamless "roadmap completes -> archived"
bridge between the two independent libraries (DESIGN + ROADMAP fonds).

Usage:
  python scripts/py/doc_archive.py --file docs/design/_outgoing/foo.md --fix
  python scripts/py/doc_archive.py --staged --fix   # pre-commit: process staged outgoing files
  python scripts/py/doc_archive.py --staged --check # gate: validate only
"""

from __future__ import annotations

import argparse
import contextlib
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
OUTGOING = ROOT / "docs/design/_outgoing"
POINTERS_JSON = ROOT / "docs/design/POINTERS.json"
ARCHIVE = ROOT / "docs/design/archive"

# fonds -> (archive dir, retention, pointer prefix)
FONDS_ARCHIVE = {
    "DESIGN": {"dir": ARCHIVE / "001-design" / "2026" / "永久", "retention": "永久", "prefix": "ARCH-DESIGN"},
    "ROADMAP": {"dir": ARCHIVE / "003-roadmap" / "2026" / "长期", "retention": "长期", "prefix": "ARCH-ROADMAP"},
}


def load_pointers() -> list[dict]:
    if POINTERS_JSON.exists():
        return json.loads(POINTERS_JSON.read_text(encoding="utf-8"))
    return []


def next_seq_for_fonds(fonds: str) -> int:
    max_seq = 0
    for p in load_pointers():
        if p.get("fonds") == fonds and p.get("status") == "archived":
            m = re.search(r"-(\d+)$", p.get("archive_number", ""))
            if m:
                with contextlib.suppress(Exception):
                    max_seq = max(max_seq, int(m.group(1)))
    return max_seq + 1


def frontmatter_of(text: str) -> dict:
    fm = {}
    if not text.startswith("---"):
        return fm
    parts = text.split("---", 2)
    if len(parts) < 3:
        return fm
    for line in parts[1].splitlines():
        m = re.match(r"^(\w+):\s*(.+)$", line.strip())
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"')
    return fm


def archive_file(path: pathlib.Path) -> tuple[str | None, str | None]:
    """Re-point frontmatter and move into the fonds archive dir.

    Returns (target_relpath, error). Requires construction: closed and a known
    fonds — the archival trigger is the completed state, never manual guessing.
    """
    text = path.read_text(encoding="utf-8", errors="ignore")
    fm = frontmatter_of(text)
    fonds = fm.get("fonds", "")
    construction = fm.get("construction", "")
    if fonds not in FONDS_ARCHIVE:
        return None, f"{path.name}: unknown fonds '{fonds}' (must be DESIGN or ROADMAP)"
    if construction != "closed":
        return None, f"{path.name}: construction must be 'closed' to archive (got '{construction}')"

    info = FONDS_ARCHIVE[fonds]
    seq = next_seq_for_fonds(fonds)
    year = "2026"
    pointer = f"{info['prefix']}-{year}-08-29-{seq:03d}"
    archive_number = f"{fonds}-{year}-{info['retention']}-{seq:03d}"
    original_name = path.name

    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_fm = False
    fm_done = False
    for ln in lines:
        if ln.strip() == "---" and not in_fm:
            in_fm = True
            out.append(ln)
            continue
        if in_fm and ln.strip() == "---":
            if not any(existing.startswith("original_name:") for existing in out):
                out.append(f"original_name: {original_name}\n")
            out.append(ln)
            fm_done = True
            continue
        if in_fm and not fm_done:
            if ln.startswith("pointer:"):
                out.append(f"pointer: {pointer}\n")
            elif ln.startswith("archive_number:"):
                out.append(f"archive_number: {archive_number}\n")
            elif ln.startswith("series:"):
                out.append("series: archive\n")
            elif ln.startswith("status:"):
                out.append("status: archived\n")
            else:
                out.append(ln)
            continue
        out.append(ln)

    info["dir"].mkdir(parents=True, exist_ok=True)
    target = info["dir"] / f"{archive_number}_{original_name}"
    target.write_text("".join(out), encoding="utf-8")
    path.unlink()
    return target.relative_to(ROOT).as_posix(), None


def handle_file(args) -> int:
    p = pathlib.Path(args.file)
    if not p.exists():
        p = ROOT / args.file
    if not p.exists():
        print(f"Error: {p} not found", file=sys.stderr)
        return 1
    if args.fix:
        target, err = archive_file(p)
        if err:
            print(f"Error: {err}", file=sys.stderr)
            return 1
        print(f"Archived {p.name} -> {target}")
        subprocess.run([sys.executable, str(ROOT / "scripts/py/generate_pointers.py")], cwd=str(ROOT))
    else:
        fm = frontmatter_of(p.read_text(encoding="utf-8", errors="ignore"))
        if fm.get("construction") != "closed":
            print(f"Gate blocked: {p.name} not construction=closed", file=sys.stderr)
            return 1
    return 0


def handle_staged(args) -> int:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=AM"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    staged = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    outgoing = [f for f in staged if "_outgoing/" in f and f.endswith(".md") and not f.endswith("README.md")]
    if not outgoing:
        return 0
    print(f"doc_archive: found {len(outgoing)} staged outgoing file(s)")
    for f in outgoing:
        p = ROOT / f
        if not p.exists():
            continue
        if args.fix:
            target, err = archive_file(p)
            if err:
                print(f"Blocked {f}: {err}", file=sys.stderr)
                return 1
            subprocess.run(["git", "rm", "--cached", f], cwd=str(ROOT), check=False)
            if target:
                subprocess.run(["git", "add", target], cwd=str(ROOT), check=False)
            print(f"Auto-archived {f} -> {target}")
        else:
            fm = frontmatter_of(p.read_text(encoding="utf-8", errors="ignore"))
            if fm.get("construction") != "closed":
                print(f"Gate blocked: {f} not construction=closed", file=sys.stderr)
                return 1
    if args.fix and outgoing:
        print("Regenerating POINTERS...")
        subprocess.run([sys.executable, str(ROOT / "scripts/py/generate_pointers.py")], cwd=str(ROOT))
        subprocess.run(["git", "add", str(POINTERS_JSON)], cwd=str(ROOT))
        db = ROOT / "docs/design/POINTERS.db"
        if db.exists():
            subprocess.run(["git", "add", "-f", str(db)], cwd=str(ROOT))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="single file in _outgoing to process")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--fix", action="store_true", help="apply the archival")
    parser.add_argument("--check", action="store_true", help="validate only")
    args = parser.parse_args()
    if args.file:
        return handle_file(args)
    if args.staged:
        return handle_staged(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
