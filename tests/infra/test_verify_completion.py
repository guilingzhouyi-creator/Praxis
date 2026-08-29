"""Regression tests for scripts/sh/verify-completion.sh — the CompletionJudge.

Covers three contracts:

1. Zero-enabled-check invocations are REFUSED (exit 2) and record nothing —
   an empty verdict measures nothing and must not pollute judge history.
2. Fast mode (any check skipped) yields PARTIAL, never COMPLETE.
3. Skipping the tests dimension prints the explicit "Tests were SKIPPED" /
   "NOT test evidence" notices.

Fast-mode tests leave exactly one cheap check enabled (`index`) so the run
exercises the real verdict path without depending on slow or env-heavy
verifiers.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "sh" / "verify-completion.sh"
ALL_CHECKS = [
    "tests",
    "coverage",
    "delta",
    "docs",
    "lint",
    "audit",
    "complex",
    "cycle",
    "singleton",
    "changelog",
    "index",
]


@pytest.fixture(autouse=True)
def _isolate_judge_log(tmp_path, monkeypatch):
    """Redirect the judge log to a temp file.

    Regression runs produce real verdict records; without redirection they
    would pollute the production judge history that docs/judge-stats.md
    aggregates (every test run would silently inflate the daily run count).
    """
    monkeypatch.setenv("JUDGE_LOG", str(tmp_path / "judge-test.jsonl"))


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _skip_all_except(keep: str) -> str:
    return "--skip=" + ",".join(c for c in ALL_CHECKS if c != keep)


def test_zero_enabled_checks_are_refused_without_a_record():
    r = _run(f"--skip={','.join(ALL_CHECKS)}")
    out = r.stdout + r.stderr
    assert r.returncode == 2
    assert "REFUSED" in out
    assert "Nothing was recorded" in out


def test_fast_mode_is_partial_never_complete():
    r = _run(_skip_all_except("index"))
    out = r.stdout + r.stderr
    assert r.returncode == 0
    assert "verdict: PARTIAL" in out
    verdict_line = next((ln for ln in out.splitlines() if "verdict:" in ln), "")
    assert "COMPLETE" not in verdict_line


def test_fast_mode_prints_tests_skipped_notice():
    # Skipping the tests dimension must surface an explicit warning so the
    # run is never mistaken for test evidence.
    r = _run(_skip_all_except("index"))
    out = r.stdout + r.stderr
    assert "Tests were SKIPPED" in out
    assert "NOT test evidence" in out
