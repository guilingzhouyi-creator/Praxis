"""Tests for scripts/py/collect_stats.py — the unified doc-stats counter.

These gate the single source of truth that feeds gen-doc-stats, gen-llms-txt
and check-doc-stats. Assert structure + reasonable thresholds rather than
brittle exact counts that drift as the codebase grows.

The full codebase scan (``collect_stats()``) is replaced by a committed
JSON snapshot (``config/quality/stats-snapshot.json``) — the test verifies
structure, not live counts. Lightweight helper functions (``health_scores``,
``count_files``, ``py_files``) are imported directly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT_PATH = ROOT / "config" / "quality" / "stats-snapshot.json"
sys.path.insert(0, str(ROOT / "scripts" / "py"))

import collect_stats  # noqa: E402 — lightweight helpers only

# Load the snapshot once at module level (fast, no Python script execution).
_STATS: dict | None = None


def _get_stats() -> dict:
    global _STATS
    if _STATS is None:
        _STATS = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return _STATS


def test_layers_shape():
    stats = _get_stats()
    assert set(stats["layers"]) == {"L1 Kernel", "L2 Shell", "L3 Cell", "L4 Bridge", "L5 User"}
    assert len(stats["sub"]) >= 5
    for _label, (n, lines) in stats["layers"].items():
        assert isinstance(n, int) and n > 0
        assert isinstance(lines, int) and lines > 0
    for _label, (n, lines) in stats["sub"].items():
        assert isinstance(n, int) and n > 0
        assert isinstance(lines, int) and lines > 0


def test_params_counts():
    stats = _get_stats()
    # Constant modules (excludes __init__.py) — the "8 params/ modules" convention.
    assert stats["params_modules"] >= 8
    assert stats["params_constants"] > 1000


def test_routes_and_domains():
    stats = _get_stats()
    assert stats["routes"] > 300
    assert stats["domains"]
    top_name, top_count = next(iter(stats["domains"].items()))
    assert isinstance(top_name, str) and isinstance(top_count, int) and top_count > 0


def test_command_counts():
    stats = _get_stats()
    assert stats["commands_yaml"] >= 40
    assert stats["commands_code"] >= 0


def test_aux_counters():
    assert collect_stats.count_files("l3/tools") > 0
    assert collect_stats.count_files("l3/cell/components") > 0
    assert collect_stats.yaml_command_count() >= 40
    assert collect_stats.code_registered_command_count() >= 0


def test_py_files_excludes_pycache(tmp_path):
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.py").write_text("")
    (tmp_path / "real.py").write_text("")
    found = {p.name for p in collect_stats.py_files(tmp_path)}
    assert found == {"real.py"}


def test_health_scores_bounds_and_keys():
    stats = _get_stats()
    h = collect_stats.health_scores(stats)
    assert set(h["scores"]) == {"test_density", "long_functions", "comment_ratio", "third_party"}
    for v in h["scores"].values():
        assert 0.0 <= v <= 1.0
    assert 0.0 <= h["overall"] <= 1.0
    assert h["grade"] in "ABCD"


def test_health_scores_extremes():
    # Perfect health: max density, no mega-functions, sweet-spot comment ratio, no deps.
    good = {
        "layers": {k: (1, 1000) for k in ("L1 Kernel", "L2 Shell", "L3 Cell", "L4 Bridge", "L5 User")},
        "test_cases": 15000,
        "long_functions": 0,
        "comment_ratio": 0.175,
        "third_party_imports": [],
    }
    h = collect_stats.health_scores(good)
    assert h["scores"]["test_density"] == 1.0
    assert h["scores"]["long_functions"] == 1.0
    assert h["scores"]["comment_ratio"] == 1.0
    assert h["scores"]["third_party"] == 1.0
    assert h["overall"] == 1.0
    assert h["grade"] == "A"

    # Worst health: no tests, many mega-functions, off sweet spot, many deps.
    bad = {
        "layers": {k: (1, 1000) for k in ("L1 Kernel", "L2 Shell", "L3 Cell", "L4 Bridge", "L5 User")},
        "test_cases": 0,
        "long_functions": 12,
        "comment_ratio": 1.0,
        "third_party_imports": [f"dep{i}" for i in range(20)],
    }
    h = collect_stats.health_scores(bad)
    assert h["scores"]["long_functions"] == 0.0
    assert h["scores"]["comment_ratio"] == 0.0
    assert h["scores"]["third_party"] == 0.0
    assert h["overall"] == 0.0
    assert h["grade"] == "D"


def test_health_scores_grade_thresholds():
    # Grade mapping: A>=0.8, B>=0.6, C>=0.4, else D — exercise each band via
    # a single uniform score so overall == that score.
    base = {
        "layers": {k: (1, 1000) for k in ("L1 Kernel", "L2 Shell", "L3 Cell", "L4 Bridge", "L5 User")},
        "test_cases": 15000,
        "long_functions": 0,
        "comment_ratio": 0.175,
        "third_party_imports": [],
    }

    def uniform(v: float) -> float:
        stats = dict(base)
        code_lines = sum(total for _n, total in stats["layers"].values())
        # test_density score = clamp((d-2)/13) with d = cases / (lines/1000) → solve cases.
        stats["test_cases"] = int((code_lines / 1000.0) * (13.0 * v + 2.0))
        # long_functions score = clamp(1 - n/12) → solve n.
        stats["long_functions"] = max(0, round(12.0 * (1.0 - v)))
        # comment_ratio score = clamp(1 - |r-0.175|/0.175) → target 0.175+0.175*(1-v).
        stats["comment_ratio"] = round(0.175 + 0.175 * (1.0 - v), 4)
        # third_party score = clamp(1 - n/20) → solve n.
        stats["third_party_imports"] = [f"dep{i}" for i in range(max(0, round(20.0 * (1.0 - v))))]
        return collect_stats.health_scores(stats)["overall"]

    assert uniform(0.9) >= 0.8  # A band
    assert 0.6 <= uniform(0.7) < 0.8  # B band
    assert 0.4 <= uniform(0.5) < 0.6  # C band
    assert uniform(0.2) < 0.4  # D band