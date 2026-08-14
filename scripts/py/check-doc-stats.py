"""Doc-stats drift gate — README numbers snapshot must match the codebase.

Runs the same counting as ``gen_doc_stats.collect_stats()`` and compares
against the "Numbers snapshot" table in docs/architecture/README.md.
Exits non-zero on any drift, so CI can gate on it:

    python scripts/py/check-doc-stats.py          # check only (CI gate)
    python scripts/py/check-doc-stats.py --fix    # rewrite the snapshot in place

Never hand-edit the numbers — regenerate instead (``make doc-stats`` runs
gen-doc-stats + gen-llms-txt; this script is the machine gate that proves
the committed snapshot is still fresh).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

from collect_stats import LAYERS, SUB_LAYERS, collect_stats, health_scores  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
README = ROOT / "docs" / "architecture" / "README.md"

# (metric label, layer name) for file/line rows — order follows README.
LAYER_ROWS = list(LAYERS.items()) + list(SUB_LAYERS.items())

_RE_FILES_LINES = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([\d,]+)\s*files\s*/\s*([\d,]+)\s*lines\s*\|")
_RE_ROUTES = re.compile(r"^\|\s*API routes\s*\|\s*(\d+)\s*")
_RE_DOMAINS = re.compile(r"^\|\s*Route domains\s*\|\s*(\d+)\s*\(")
_RE_PARAMS = re.compile(r"^\|\s*Params modules / constants\s*\|\s*(\d+)\s*/\s*([\d,]+)\s*\|")
_RE_HEALTH = re.compile(r"^\|\s*Health\s*\|\s*([\d.]+)\s*\(grade\s*([A-D])\s*\)\s*\|")


def _fmt(n: int) -> str:
    return f"{n:,}"


def snapshot_rows(stats: dict) -> dict[str, str]:
    """Build the canonical table rows from live stats (label -> full row)."""
    rows: dict[str, str] = {}
    for _rel, label in LAYER_ROWS:
        n, lines = stats["layers"][label] if label in stats["layers"] else stats["sub"][label]
        rows[label] = f"| {label} | {n} files / {_fmt(lines)} lines |"
    rows["API routes"] = f"| API routes | {stats['routes']} (`/api/v2/*` versioned) |"
    top = list(stats["domains"].items())[:5]
    largest = ", ".join(f"{d}={n}" for d, n in top)
    rows["Route domains"] = f"| Route domains | {len(stats['domains'])} (largest: {largest}) |"
    rows["Params modules / constants"] = (
        f"| Params modules / constants | {stats['params_modules']} / {_fmt(stats['params_constants'])} |"
    )
    h = health_scores(stats)
    rows["Health"] = f"| Health | {h['overall']:.3f} (grade {h['grade']}) |"
    return rows


def parse_readme() -> dict[str, str]:
    """Extract label -> row text from the current README snapshot table."""
    found: dict[str, str] = {}
    in_table = False
    for line in README.read_text(encoding="utf-8").splitlines():
        if line.strip() == "| Metric | Value |":
            in_table = True
            continue
        if not in_table:
            continue
        if line.strip().startswith("|") and line.strip().endswith("|"):
            m = _RE_FILES_LINES.match(line)
            if m:
                found[m.group(1).strip()] = line
                continue
            m = _RE_ROUTES.match(line)
            if m:
                found["API routes"] = line
                continue
            m = _RE_DOMAINS.match(line)
            if m:
                found["Route domains"] = line
                continue
            m = _RE_PARAMS.match(line)
            if m:
                found["Params modules / constants"] = line
                continue
            m = _RE_HEALTH.match(line)
            if m:
                found["Health"] = line
                continue
        else:
            in_table = False
    return found


def check(stats: dict, current: dict[str, str]) -> list[str]:
    """Return a list of drift messages (empty = in sync)."""
    drift: list[str] = []
    for label, row in snapshot_rows(stats).items():
        if label not in current:
            drift.append(f"missing row for {label!r}")
        elif current[label].strip() != row.strip():
            drift.append(f"{label}:\n  README: {current[label].strip()}\n  live:   {row.strip()}")
    return drift


def fix(stats: dict, current: dict[str, str]) -> tuple[int, list[str]]:
    """Rewrite the snapshot rows in README.md in place.

    Returns (replaced_count, still_missing): rows actually rewritten and
    canonical labels that were absent from the table and could not be
    matched by label (they must be inserted by the caller or reported).
    """
    rows = snapshot_rows(stats)
    text = README.read_text(encoding="utf-8")
    replaced = 0
    for label, row in rows.items():
        if label in current:
            text = text.replace(current[label], row)
            replaced += 1
    README.write_text(text, encoding="utf-8")
    still_missing = [label for label in rows if label not in current]
    return replaced, still_missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Doc-stats drift gate")
    parser.add_argument("--fix", action="store_true", help="rewrite README snapshot in place")
    args = parser.parse_args()

    stats = collect_stats()
    current = parse_readme()
    drift = check(stats, current)

    if not drift:
        print("README numbers snapshot is in sync with the codebase.")
        return 0

    if args.fix:
        replaced, still_missing = fix(stats, current)
        print(f"README numbers snapshot updated ({replaced} rows).")
        if still_missing:
            print("MISSING rows (not in README table, add them manually):")
            for label in still_missing:
                print(f" - {label}: {snapshot_rows(stats)[label]}")
        # Re-check after the rewrite — a fix that leaves drift must fail.
        if check(stats, parse_readme()):
            print("ERROR: drift remains after --fix.")
            return 1
        return 0

    print("DRIFT: README numbers snapshot does not match the live codebase.")
    for msg in drift:
        print(" -", msg)
    print("Run `python scripts/py/check-doc-stats.py --fix` (or `make doc-stats`) to update.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
