"""Contract tests for the independent Rust/Python R2 benchmark boundary."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "py"))

from r2_reference_bench import build_evidence  # noqa: E402


def test_python_reference_preserves_fixed_work_and_resource_units() -> None:
    """The Python reference emits complete samples with explicit resources."""
    evidence = build_evidence(total_work=16, workers=(1, 2), rounds=1, capacity=2)

    assert evidence["schema_version"] == 3
    assert evidence["metadata"]["resource_sampling"] == {
        "cpu_unit": "ns",
        "memory_unit": "bytes",
        "scope": "process_round_delta",
    }
    samples = evidence["report"]["samples"]
    assert len(samples) == 2
    assert all(sample["completed_work_items"] == 16 for sample in samples)
    assert all(sample["p99_latency_ns"] >= sample["p95_latency_ns"] for sample in samples)
    assert all("cpu_source" in sample["resources"] for sample in samples)


def test_python_reference_rejects_invalid_capacity() -> None:
    """A zero-capacity queue fails before worker threads are started."""
    try:
        build_evidence(total_work=4, workers=(1,), rounds=1, capacity=0)
    except ValueError:
        return
    raise AssertionError("zero queue capacity must be rejected")
