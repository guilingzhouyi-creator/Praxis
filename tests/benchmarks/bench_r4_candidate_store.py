"""Benchmark R4 candidate-ledger ingestion and the deferred durability barrier.

Run with ``python tests/benchmarks/bench_r4_candidate_store.py``. The report
separates hot-path submission throughput from the explicit ``flush()`` barrier
so Rust-sink planning can compare in-memory ingestion with journal durability.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "systems/python-reference-runtime"))

from l3.memory.r4_candidate_store import CandidateStore  # noqa: E402
from l4.params import EVAL_AMDAHL_ROUNDS, EVAL_PERSIST_ITERS


def _record(index: int) -> dict[str, str]:
    """Build one same-cluster record with unique evidence identity."""
    return {
        "entry_id": f"benchmark-{index}",
        "entry_type": "benchmark",
        "cell_id": "bench-cell",
        "agent_id": "bench-agent",
        "role": "bench",
        "content": "candidate ledger benchmark",
    }


def _run_once(records: int) -> tuple[float, float]:
    """Measure submission and post-submission flush times in an isolated ledger."""
    with tempfile.TemporaryDirectory() as directory:
        store = CandidateStore(os.path.join(directory, "candidates.json"))
        start = time.perf_counter()
        for index in range(records):
            store.submit_records([_record(index)])
        submitted_at = time.perf_counter()
        store.flush()
        return submitted_at - start, time.perf_counter() - start


def _median(values: list[float]) -> float:
    """Return the middle measurement after sorting."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def run(records: int, rounds: int) -> dict[str, float]:
    """Report median hot-path and durable throughput for candidate ingestion."""
    submissions: list[float] = []
    durable: list[float] = []
    for _ in range(rounds):
        submission_wall, durable_wall = _run_once(records)
        submissions.append(submission_wall)
        durable.append(durable_wall)
    submission_wall = _median(submissions)
    durable_wall = _median(durable)
    return {
        "records": float(records),
        "submit_ops_per_sec": records / submission_wall if submission_wall else 0.0,
        "durable_ops_per_sec": records / durable_wall if durable_wall else 0.0,
        "flush_seconds": durable_wall - submission_wall,
    }


def main() -> int:
    """Parse benchmark options and print a compact performance report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=EVAL_PERSIST_ITERS)
    parser.add_argument("--rounds", type=int, default=EVAL_AMDAHL_ROUNDS)
    args = parser.parse_args()
    result = run(args.records, args.rounds)
    print("R4 candidate ledger benchmark")
    for key, value in result.items():
        print(f"{key}: {value:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
