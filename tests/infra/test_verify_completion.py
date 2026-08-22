"""Regression tests for scripts/sh/verify-completion.sh — the CompletionJudge.

Covers the anti "forgot the tests" behavior: a fast-mode run that skips the
tests dimension must yield PARTIAL (never COMPLETE) and print the explicit
"Tests were SKIPPED" notice.
"""

from __future__ import annotations

import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "sh" / "verify-completion.sh"
SKIP_ALL = "tests,coverage,delta,docs,lint,audit,complex,cycle,singleton,changelog,index"


def _run_fast() -> subprocess.CompletedProcess[str]:
    """Run the judge with every check skipped (fast mode)."""
    return subprocess.run(
        ["bash", str(SCRIPT), f"--skip={SKIP_ALL}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_fast_mode_is_partial_never_complete():
    r = _run_fast()
    out = r.stdout + r.stderr
    assert "verdict: PARTIAL" in out
    verdict_line = next((ln for ln in out.splitlines() if "verdict:" in ln), "")
    assert "COMPLETE" not in verdict_line


def test_fast_mode_prints_tests_skipped_notice():
    # Skipping the tests dimension must surface an explicit warning so the
    # run is never mistaken for test evidence.
    r = _run_fast()
    out = r.stdout + r.stderr
    assert "Tests were SKIPPED" in out
    assert "NOT test evidence" in out
