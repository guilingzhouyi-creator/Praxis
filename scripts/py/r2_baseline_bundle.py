"""Compose independent Rust and Python R2 fixed-work evidence."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUST_MANIFEST = ROOT / "systems" / "rust-kernel-engine" / "Cargo.toml"
PYTHON_REFERENCE = ROOT / "scripts" / "py" / "r2_reference_bench.py"
BUNDLE_SCHEMA_VERSION = 1
EVIDENCE_SCHEMA_VERSION = 3
EXPECTED_WORKLOAD = "substrate.queue.contention"
EXPECTED_TOTAL_WORK = 4_096
EXPECTED_WORKERS = [1, 2, 4]
EXPECTED_ROUNDS = 3


def _source_revision() -> str:
    """Return an explicit revision for evidence attribution."""
    configured = os.environ.get("PRAXIS_GIT_REVISION", "").strip()
    if configured:
        return configured
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"


def _run_json(command: list[str], *, environment: dict[str, str], timeout: int = 240) -> dict[str, Any]:
    """Run an evidence producer and parse its stdout as JSON."""
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        detail = (result.stdout + result.stderr).strip()[-1_000:]
        raise RuntimeError(f"evidence producer failed ({result.returncode}): {detail}")
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"evidence producer emitted invalid JSON: {error}") from error
    if not isinstance(document, dict):
        raise RuntimeError("evidence producer root must be an object")
    return document


def _validate_evidence(name: str, evidence: dict[str, Any]) -> None:
    """Validate the shared fixed-work and resource contract."""
    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError(f"{name} evidence schema is not {EVIDENCE_SCHEMA_VERSION}")
    metadata = evidence.get("metadata")
    report = evidence.get("report")
    if not isinstance(metadata, dict) or not isinstance(report, dict):
        raise ValueError(f"{name} evidence requires metadata and report objects")
    sampling = metadata.get("resource_sampling")
    if sampling != {"cpu_unit": "ns", "memory_unit": "bytes", "scope": "process_round_delta"}:
        raise ValueError(f"{name} resource sampling metadata is not unified")
    spec = report.get("spec")
    samples = report.get("samples")
    if (
        report.get("schema_version") != EVIDENCE_SCHEMA_VERSION
        or not isinstance(spec, dict)
        or not isinstance(samples, list)
    ):
        raise ValueError(f"{name} report is malformed")
    expected = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "workload": EXPECTED_WORKLOAD,
        "total_work_items": EXPECTED_TOTAL_WORK,
        "workers": EXPECTED_WORKERS,
        "rounds": EXPECTED_ROUNDS,
    }
    if spec != expected:
        raise ValueError(f"{name} fixed-work specification differs from the bundle contract")
    expected_pairs = {(worker, round_number) for worker in EXPECTED_WORKERS for round_number in range(EXPECTED_ROUNDS)}
    observed_pairs: set[tuple[int, int]] = set()
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError(f"{name} contains a non-object sample")
        pair = (sample.get("workers"), sample.get("round"))
        if pair in observed_pairs or pair not in expected_pairs:
            raise ValueError(f"{name} contains duplicate or unknown worker/round sample")
        observed_pairs.add(pair)
        if sample.get("completed_work_items") != EXPECTED_TOTAL_WORK or sample.get("elapsed_ns", 0) <= 0:
            raise ValueError(f"{name} does not preserve fixed work")
        if sample.get("p99_latency_ns", 0) < sample.get("p95_latency_ns", 0):
            raise ValueError(f"{name} p99 latency is below p95 latency")
        if sample.get("errors", 0) > EXPECTED_TOTAL_WORK:
            raise ValueError(f"{name} error count exceeds fixed work")
        resources = sample.get("resources")
        if not isinstance(resources, dict):
            raise ValueError(f"{name} sample lacks resource measurements")
        for value_key, source_key in (("cpu_time_ns", "cpu_source"), ("memory_bytes", "memory_source")):
            value = resources.get(value_key)
            source = resources.get(source_key)
            if not isinstance(source, str) or not source:
                raise ValueError(f"{name} resource source is missing")
            if (value is None) != (source == "unavailable"):
                raise ValueError(f"{name} resource value/source availability disagrees")
    if observed_pairs != expected_pairs:
        raise ValueError(f"{name} is missing worker/round samples")


def build_bundle() -> dict[str, Any]:
    """Run both producers and return one validated comparison bundle."""
    revision = _source_revision()
    environment = os.environ.copy()
    environment["PRAXIS_GIT_REVISION"] = revision
    rust = _run_json(
        ["cargo", "run", "--manifest-path", str(RUST_MANIFEST), "--release", "--bin", "rust-kernel-bench"],
        environment=environment,
    )
    python_reference = _run_json([sys.executable, str(PYTHON_REFERENCE)], environment=environment)
    _validate_evidence("rust", rust)
    _validate_evidence("python", python_reference)
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_revision": revision,
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine() or "unknown",
            "cpu_count": os.cpu_count() or 0,
        },
        "workload": {
            "workload": EXPECTED_WORKLOAD,
            "total_work_items": EXPECTED_TOTAL_WORK,
            "workers": EXPECTED_WORKERS,
            "rounds": EXPECTED_ROUNDS,
            "queue_capacity": 64,
        },
        "evidence": {"rust": rust, "python": python_reference},
    }


def main() -> int:
    """Parse options, run both baselines, and write the comparison bundle."""
    parser = argparse.ArgumentParser(description="Build the Rust/Python R2 evidence bundle")
    parser.add_argument("--output", type=Path, required=True, help="path for the generated bundle JSON")
    args = parser.parse_args()
    bundle = build_bundle()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"R2 baseline bundle written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
