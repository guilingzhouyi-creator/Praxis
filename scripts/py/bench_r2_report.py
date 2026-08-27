"""Analyze a validated Rust/Python R2 fixed-work evidence bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bench_r2_bundle import (
    BUNDLE_SCHEMA_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    EXPECTED_ROUNDS,
    EXPECTED_TOTAL_WORK,
    EXPECTED_WORKERS,
    EXPECTED_WORKLOAD,
    _validate_evidence,
)

ANALYSIS_SCHEMA_VERSION = 1
NANOSECONDS_PER_SECOND = 1_000_000_000
DEFAULT_INPUT = Path(".praxis/automation/r2-baseline-bundle.json")


def _median(values: list[int]) -> int:
    """Return the nearest-rank middle value for deterministic summaries."""
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def _optional_median(values: list[int | None]) -> int | None:
    """Return a resource median while preserving unavailable samples."""
    available = [value for value in values if value is not None]
    return _median(available) if available else None


def _ratio(numerator: int, denominator: int) -> float | None:
    """Return a ratio or null when the denominator cannot support comparison."""
    if denominator <= 0:
        return None
    return numerator / denominator


def _throughput(sample: dict[str, Any]) -> int:
    """Derive integer fixed-work throughput from one raw sample."""
    elapsed_ns = int(sample["elapsed_ns"])
    completed = int(sample["completed_work_items"])
    return completed * NANOSECONDS_PER_SECOND // elapsed_ns


def _worker_summary(samples: list[dict[str, Any]], total_work: int) -> dict[str, Any]:
    """Summarize one worker count without hiding round-level drops."""
    throughput = [_throughput(sample) for sample in samples]
    p95 = [int(sample["p95_latency_ns"]) for sample in samples]
    p99 = [int(sample["p99_latency_ns"]) for sample in samples]
    queue_wait = [int(sample["queue_wait_ns"]) for sample in samples]
    lock_wait = [int(sample["lock_wait_ns"]) for sample in samples]
    rejected = sum(int(sample["rejected"]) for sample in samples)
    errors = sum(int(sample["errors"]) for sample in samples)
    attempts = total_work * len(samples) + rejected
    resources = [sample["resources"] for sample in samples]
    cpu_values = [resource.get("cpu_time_ns") for resource in resources]
    memory_values = [resource.get("memory_bytes") for resource in resources]
    return {
        "rounds": len(samples),
        "throughput_ops_per_sec": {
            "median": _median(throughput),
            "min": min(throughput),
            "max": max(throughput),
        },
        "p95_latency_ns": {"median": _median(p95), "max": max(p95)},
        "p99_latency_ns": {"median": _median(p99), "max": max(p99)},
        "queue_wait_ns": {"median": _median(queue_wait), "max": max(queue_wait)},
        "lock_wait_ns": {"median": _median(lock_wait), "max": max(lock_wait)},
        "rejected": {
            "total": rejected,
            "ratio": _ratio(rejected, attempts),
        },
        "errors": {
            "total": errors,
            "ratio": _ratio(errors, total_work * len(samples)),
        },
        "resources": {
            "cpu_time_ns": {
                "median": _optional_median(cpu_values),
                "available_samples": sum(value is not None for value in cpu_values),
            },
            "memory_bytes": {
                "median": _optional_median(memory_values),
                "available_samples": sum(value is not None for value in memory_values),
            },
        },
    }


def _scaling(summary_by_worker: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare each worker count with the smallest configured worker count."""
    worker_counts = sorted(int(worker) for worker in summary_by_worker)
    baseline_worker = worker_counts[0]
    baseline = summary_by_worker[str(baseline_worker)]["throughput_ops_per_sec"]["median"]
    result: dict[str, Any] = {"baseline_workers": baseline_worker, "workers": {}}
    for worker in worker_counts:
        median = summary_by_worker[str(worker)]["throughput_ops_per_sec"]["median"]
        ratio = _ratio(median, baseline)
        result["workers"][str(worker)] = {
            "throughput_ratio": ratio,
            "scaling_efficiency": None if ratio is None else ratio / worker,
        }
    return result


def _compare_languages(rust: dict[str, dict[str, Any]], python: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare Rust and Python summaries without declaring a cutover winner."""
    comparisons: dict[str, Any] = {}
    for worker in sorted(rust, key=int):
        rust_summary = rust[worker]
        python_summary = python[worker]
        rust_throughput = rust_summary["throughput_ops_per_sec"]["median"]
        python_throughput = python_summary["throughput_ops_per_sec"]["median"]
        rust_p95 = rust_summary["p95_latency_ns"]["median"]
        python_p95 = python_summary["p95_latency_ns"]["median"]
        comparisons[worker] = {
            "throughput_rust_over_python": _ratio(rust_throughput, python_throughput),
            "p95_latency_rust_over_python": _ratio(rust_p95, python_p95),
            "rejected_ratio_delta_rust_minus_python": (
                rust_summary["rejected"]["ratio"] - python_summary["rejected"]["ratio"]
                if rust_summary["rejected"]["ratio"] is not None and python_summary["rejected"]["ratio"] is not None
                else None
            ),
        }
    return comparisons


def analyze_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Validate and summarize one complete R2 comparison bundle."""
    if bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported R2 bundle schema version")
    if bundle.get("evidence_schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported R2 evidence schema version")
    workload = bundle.get("workload")
    expected_workload = {
        "workload": EXPECTED_WORKLOAD,
        "total_work_items": EXPECTED_TOTAL_WORK,
        "workers": EXPECTED_WORKERS,
        "rounds": EXPECTED_ROUNDS,
        "queue_capacity": 64,
    }
    if workload != expected_workload:
        raise ValueError("R2 bundle workload differs from the analysis contract")
    evidence = bundle.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != {"rust", "python"}:
        raise ValueError("R2 bundle must contain exactly rust and python evidence")
    for name, document in evidence.items():
        if not isinstance(document, dict):
            raise ValueError(f"{name} evidence must be an object")
        _validate_evidence(name, document)

    summaries: dict[str, dict[str, Any]] = {}
    for name, document in evidence.items():
        by_worker: dict[str, list[dict[str, Any]]] = {}
        for sample in document["report"]["samples"]:
            by_worker.setdefault(str(sample["workers"]), []).append(sample)
        summaries[name] = {
            worker: _worker_summary(samples, EXPECTED_TOTAL_WORK)
            for worker, samples in sorted(by_worker.items(), key=lambda item: int(item[0]))
        }

    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "source_revision": bundle.get("source_revision", "unknown"),
        "workload": expected_workload,
        "integrity": {
            "fixed_work_complete": True,
            "resource_contract_valid": True,
            "execution_errors": {
                name: sum(summary["errors"]["total"] for summary in by_worker.values())
                for name, by_worker in summaries.items()
            },
        },
        "descriptive_analysis": {
            name: {
                "by_worker": by_worker,
                "scaling": _scaling(by_worker),
            }
            for name, by_worker in summaries.items()
        },
        "language_comparison": _compare_languages(summaries["rust"], summaries["python"]),
        "decision": "evidence_only",
    }


def main() -> int:
    """Parse an evidence path and emit a deterministic analysis document."""
    parser = argparse.ArgumentParser(description="Analyze the Rust/Python R2 evidence bundle")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    bundle = json.loads(args.input.read_text(encoding="utf-8"))
    document = json.dumps(analyze_bundle(bundle), indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
    print(document, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
