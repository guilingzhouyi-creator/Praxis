"""Contract tests for descriptive R2 bundle analysis."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "py"))

from bench_r2_report import analyze_bundle  # noqa: E402


def _bundle() -> dict:
    """Build a small deterministic bundle-shaped document without subprocesses."""
    samples = {}
    for name, multiplier in (("rust", 2), ("python", 1)):
        rows = []
        for workers in (1, 2, 4):
            for round_number in range(3):
                rows.append(
                    {
                        "workers": workers,
                        "round": round_number,
                        "completed_work_items": 4_096,
                        "elapsed_ns": 4_096 * 1_000 // (multiplier * workers),
                        "p95_latency_ns": 10 * workers,
                        "p99_latency_ns": 12 * workers,
                        "queue_wait_ns": 2,
                        "lock_wait_ns": 3,
                        "rejected": workers,
                        "errors": 0,
                        "resources": {
                            "cpu_time_ns": 100 * multiplier,
                            "memory_bytes": 2_048,
                            "cpu_source": "test.cpu",
                            "memory_source": "test.memory",
                        },
                    }
                )
        samples[name] = {
            "schema_version": 3,
            "metadata": {
                "platform": "test",
                "architecture": "test",
                "runtime": name,
                "git_revision": "test",
                "runner": "test",
                "resource_sampling": {
                    "cpu_unit": "ns",
                    "memory_unit": "bytes",
                    "scope": "process_round_delta",
                },
            },
            "report": {
                "schema_version": 3,
                "spec": {
                    "schema_version": 3,
                    "workload": "substrate.queue.contention",
                    "total_work_items": 4_096,
                    "workers": [1, 2, 4],
                    "rounds": 3,
                },
                "samples": rows,
            },
        }
    return {
        "schema_version": 1,
        "evidence_schema_version": 3,
        "source_revision": "test",
        "workload": {
            "workload": "substrate.queue.contention",
            "total_work_items": 4_096,
            "workers": [1, 2, 4],
            "rounds": 3,
            "queue_capacity": 64,
        },
        "evidence": samples,
    }


def test_analysis_reports_scaling_drop_and_language_comparison() -> None:
    """Analysis preserves fixed work and exposes descriptive ratios."""
    report = analyze_bundle(_bundle())

    assert report["decision"] == "evidence_only"
    assert report["integrity"]["execution_errors"] == {"rust": 0, "python": 0}
    assert report["descriptive_analysis"]["rust"]["scaling"]["baseline_workers"] == 1
    assert report["descriptive_analysis"]["rust"]["scaling"]["workers"]["2"]["scaling_efficiency"] == 1.0
    assert report["language_comparison"]["1"]["throughput_rust_over_python"] == 2.0
    assert report["descriptive_analysis"]["rust"]["by_worker"]["4"]["queue_wait_ns"]["median"] == 2
    assert report["descriptive_analysis"]["rust"]["by_worker"]["4"]["lock_wait_ns"]["median"] == 3
    assert report["descriptive_analysis"]["python"]["by_worker"]["4"]["rejected"]["total"] == 12


def test_analysis_rejects_a_mixed_fixed_work_spec() -> None:
    """A bundle with a different worker sweep cannot be analyzed."""
    bundle = _bundle()
    bundle["workload"]["workers"] = [1, 2]

    try:
        analyze_bundle(bundle)
    except ValueError as error:
        assert "workload" in str(error)
    else:
        raise AssertionError("mixed fixed-work specification must be rejected")
