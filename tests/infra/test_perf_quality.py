"""Tests for the performance baseline comparison and reporting policy."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "py"))

from perf_quality import compare, emit_baseline, render_report  # noqa: E402


def test_missing_baseline_is_blocking_by_default() -> None:
    """A measured metric without a baseline must fail the normal gate."""
    findings = compare({"L2": {"protocol.ops_per_sec": 100.0}}, {"layers": {"L2": {}}})

    assert findings[0]["kind"] == "hard"
    assert "FAIL:" in render_report({"L2": {"protocol.ops_per_sec": 100.0}}, findings)


def test_missing_baseline_can_be_explicitly_non_blocking() -> None:
    """Migration scans may opt into visible, non-blocking missing-baseline notices."""
    measured = {"L2": {"protocol.ops_per_sec": 100.0}}
    findings = compare(measured, {"layers": {"L2": {}}}, allow_missing_baseline=True)
    report = render_report(measured, findings)

    assert findings[0]["kind"] == "notice"
    assert "NOTICE:" in report
    assert "PASS:" in report
    assert "FAIL:" not in report


def test_emit_baseline_layer_preserves_unselected_layers() -> None:
    """Layer-scoped baseline generation leaves unrelated values untouched."""
    output = emit_baseline(
        {"L2": {"protocol.ops_per_sec": 123.0}},
        {"layers": {"L1": {"mutex.acquire_release": 456.0}}},
    )

    assert "mutex.acquire_release: 456.000" in output
    assert "protocol.ops_per_sec: 123.000" in output
