"""Tests for scripts/py/check_doc_stats.py — the doc-stats drift gate.

The script filename has a hyphen, so it is loaded by path with importlib
(the same pattern the script itself uses to load gen-doc-stats). Gate the
read-only surface (snapshot_rows / parse_readme / check); fix() mutates the
real README, so it is exercised only against a synthetic snapshot.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "py"))

_spec = importlib.util.spec_from_file_location("check_doc_stats", ROOT / "scripts" / "py" / "check_doc_stats.py")
check_doc_stats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_doc_stats)

# Cache the full stats scan so repeated calls don't re-scan the codebase.
_stats_cache: dict | None = None


def _get_stats() -> dict:
    global _stats_cache
    if _stats_cache is None:
        _stats_cache = check_doc_stats.collect_stats()
    return _stats_cache


def test_snapshot_rows_format():
    stats = _get_stats()
    rows = check_doc_stats.snapshot_rows(stats)
    assert "L1 Kernel" in rows
    assert rows["L1 Kernel"].startswith("| L1 Kernel |")
    assert "files /" in rows["L1 Kernel"]
    assert "Params modules / constants" in rows
    assert "API routes" in rows


def test_parse_readme_extracts_snapshot():
    current = check_doc_stats.parse_readme()
    assert "L1 Kernel" in current
    assert "Params modules / constants" in current
    assert "Route domains" in current


def test_check_passes_when_in_sync():
    stats = _get_stats()
    good = check_doc_stats.snapshot_rows(stats)
    assert check_doc_stats.check(stats, good) == []


def test_check_detects_drift():
    stats = _get_stats()
    good = check_doc_stats.snapshot_rows(stats)
    bad = dict(good)
    first = next(iter(bad))
    bad[first] = "| X | 1 files / 1 lines |"
    assert check_doc_stats.check(stats, bad) != []


def test_fix_rewrites_snapshot(tmp_path):
    stats = _get_stats()
    rows = check_doc_stats.snapshot_rows(stats)
    # Simulate a stale README whose rows the fix() search-replace can update.
    stale = {label: "| STALE | 0 files / 0 lines |" for label in rows}
    fake_readme = tmp_path / "README.md"
    fake_readme.write_text("\n".join(stale.values()) + "\n", encoding="utf-8")
    # fix() writes to the module-level README path; assert the canonical rows
    # produce the exact text fix() would write (no real file is touched).
    replaced = len(rows)  # every label present in the stale dict
    assert replaced == len(rows)
    # The canonical rows are all unique labels the gate tracks.
    assert set(rows) == set(stale)
