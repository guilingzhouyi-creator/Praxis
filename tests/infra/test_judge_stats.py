"""Tests for scripts/sh/judge-stats.sh — the CompletionJudge dashboard aggregator.

Feeds synthetic judge-run JSONL via --log= and asserts the JSON output
exposes the extended dimensions: per-branch completion, duration avg/P95,
longest INCOMPLETE streak, check pass rates, failure pairs, metrics trends,
and gate exemptions.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
STATS = ROOT / "scripts" / "sh" / "judge-stats.sh"

# Three runs: two INCOMPLETE on feature branches (one with a failure pair,
# one clean-ish), one COMPLETE on main — plus numeric metrics.
RUNS = [
    {
        "ts": "2026-08-14T10:00:00Z",
        "verdict": "INCOMPLETE",
        "branch": "feature/alpha",
        "duration_s": 20,
        "checks": {
            "tests": 1,
            "coverage": 1,
            "delta": 1,
            "docs": 1,
            "lint": 2,
            "audit": 1,
            "complex": 1,
            "cycle": 1,
            "singleton": 1,
            "changelog": 2,
            "index": 1,
        },
        "metrics": {
            "tests_passed": 100,
            "tests_failed": 0,
            "coverage_pct": 62,
            "net_delta": 500,
            "ruff_errors": 4,
            "mega_funcs": 3,
            "audit_vulns": 0,
        },
    },
    {
        "ts": "2026-08-14T11:00:00Z",
        "verdict": "INCOMPLETE",
        "branch": "feature/alpha",
        "duration_s": 30,
        "checks": {
            "tests": 1,
            "coverage": 1,
            "delta": 2,
            "docs": 1,
            "lint": 2,
            "audit": 1,
            "complex": 1,
            "cycle": 1,
            "singleton": 1,
            "changelog": 2,
            "index": 1,
        },
        "metrics": {
            "tests_passed": 100,
            "tests_failed": 0,
            "coverage_pct": 63,
            "net_delta": 500,
            "ruff_errors": 5,
            "mega_funcs": 3,
            "audit_vulns": 0,
        },
    },
    {
        "ts": "2026-08-14T12:00:00Z",
        "verdict": "COMPLETE",
        "branch": "main",
        "duration_s": 15,
        "checks": {
            "tests": 1,
            "coverage": 1,
            "delta": 1,
            "docs": 1,
            "lint": 1,
            "audit": 1,
            "complex": 1,
            "cycle": 1,
            "singleton": 1,
            "changelog": 1,
            "index": 1,
        },
        "metrics": {
            "tests_passed": 100,
            "tests_failed": 0,
            "coverage_pct": 64,
            "net_delta": 1000,
            "ruff_errors": 0,
            "mega_funcs": 3,
            "audit_vulns": 0,
        },
    },
]


def write_log(tmp_path: Path) -> Path:
    """Write synthetic runs to a temp JSONL file and return its path."""
    log = tmp_path / "judge-runs.jsonl"
    with open(log, "w", encoding="utf-8") as f:
        for r in RUNS:
            f.write(json.dumps(r) + "\n")
    return log


def run_stats(log: Path, *extra: str) -> dict:
    """Run judge-stats.sh --json against the given log, returning parsed JSON."""
    result = subprocess.run(
        ["bash", str(STATS), "--json", f"--log={log}", *extra],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_total_and_rate(tmp_path):
    data = run_stats(write_log(tmp_path))
    assert data["total"] == 3
    assert data["complete"] == 1
    assert data["incomplete"] == 2
    assert data["completion_rate"] == round(1 / 3, 3)


def test_branch_dimension(tmp_path):
    data = run_stats(write_log(tmp_path))
    assert data["branch_stats"]["feature/alpha"]["runs"] == 2
    assert data["branch_stats"]["feature/alpha"]["complete"] == 0
    assert data["branch_stats"]["main"]["complete"] == 1
    assert data["branch_stats"]["main"]["rate"] == 1.0


def test_duration_stats(tmp_path):
    data = run_stats(write_log(tmp_path))
    # durations [15, 20, 30] → avg 21.7, P95 (index 2) = 30
    assert data["duration_s"]["avg"] == round((15 + 20 + 30) / 3, 1)
    assert data["duration_s"]["p95"] == 30


def test_incomplete_streak(tmp_path):
    data = run_stats(write_log(tmp_path))
    # chronological: INCOMPLETE, INCOMPLETE, COMPLETE → max streak 2
    assert data["max_incomplete_streak"] == 2


def test_failures_by_check(tmp_path):
    data = run_stats(write_log(tmp_path))
    assert data["failures_by_check"]["lint"] == 2
    assert data["failures_by_check"]["changelog"] == 2
    assert data["failures_by_check"]["delta"] == 1


def test_failure_pairs(tmp_path):
    data = run_stats(write_log(tmp_path))
    # pairs are sorted alphabetically: run1 lint+changelog → "changelog+lint";
    # run2 delta+lint+changelog adds "changelog+delta" and "delta+lint".
    assert any("changelog+lint" in p for p in data["failure_pairs"])
    assert any("changelog+delta" in p for p in data["failure_pairs"])


def test_metrics_trend(tmp_path):
    data = run_stats(write_log(tmp_path))
    cov = data["metrics"]["coverage_pct"]
    assert cov["latest"] == 64.0
    assert cov["avg"] == round((62 + 63 + 64) / 3, 2)
    assert cov["min"] == 62.0
    assert cov["max"] == 64.0
    assert data["metrics"]["ruff_errors"]["latest"] == 0.0


def test_check_pass_rates(tmp_path):
    data = run_stats(write_log(tmp_path))
    # lint executed 3 times, passed once → 1/3
    assert data["check_pass_rates"]["lint"] == {"pass": 1, "executed": 3, "rate": round(1 / 3, 3)}


def test_md_output(tmp_path):
    log = write_log(tmp_path)
    result = subprocess.run(
        ["bash", str(STATS), "--md", f"--log={log}"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    md = result.stdout
    assert "**Runs**: 3" in md
    assert "**Duration**: avg 22s / P95 30s" in md
    assert "**Longest INCOMPLETE streak**: 2 consecutive" in md
    assert "**Completion rate by branch**" in md
    assert "**Check pass rate**" in md
    assert "**Numeric metrics**" in md
    assert "`coverage_pct`" in md
