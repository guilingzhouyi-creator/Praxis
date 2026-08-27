"""Run the Python reference for the fixed-work R2 queue baseline."""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3
CPU_TIME_UNIT = "ns"
MEMORY_UNIT = "bytes"
RESOURCE_SCOPE = "process_round_delta"
UNAVAILABLE = "unavailable"
DEFAULT_WORKLOAD = "substrate.queue.contention"
DEFAULT_TOTAL_WORK = 4_096
DEFAULT_WORKERS = (1, 2, 4)
DEFAULT_ROUNDS = 3
DEFAULT_CAPACITY = 64


def _git_revision() -> str:
    """Return the caller-supplied source revision or an explicit fallback."""
    return os.environ.get("PRAXIS_GIT_REVISION", "unknown") or "unknown"


def _rss_hwm_bytes() -> tuple[int | None, str]:
    """Return process high-water RSS in bytes when the host exposes it."""
    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform != "darwin":
            value *= 1024
        return value, "python.resource.ru_maxrss"
    except (ImportError, OSError, AttributeError, ValueError):
        return None, UNAVAILABLE


def _resource_snapshot() -> tuple[int | None, int | None, str, str]:
    """Capture process CPU time and high-water RSS with source attribution."""
    try:
        cpu_time_ns: int | None = time.process_time_ns()
        cpu_source = "python.time.process_time_ns"
    except AttributeError:
        cpu_time_ns = None
        cpu_source = UNAVAILABLE
    memory_bytes, memory_source = _rss_hwm_bytes()
    return cpu_time_ns, memory_bytes, cpu_source, memory_source


def _resource_delta(
    before: tuple[int | None, int | None, str, str], after: tuple[int | None, int | None, str, str]
) -> dict[str, Any]:
    """Convert cumulative process observations into one round delta."""
    cpu_start, memory_start, _, _ = before
    cpu_end, memory_end, cpu_source, memory_source = after
    cpu_time_ns = None if cpu_start is None or cpu_end is None else max(0, cpu_end - cpu_start)
    memory_bytes = None if memory_start is None or memory_end is None else max(0, memory_end - memory_start)
    return {
        "cpu_time_ns": cpu_time_ns,
        "memory_bytes": memory_bytes,
        "cpu_source": cpu_source if cpu_time_ns is not None else UNAVAILABLE,
        "memory_source": memory_source if memory_bytes is not None else UNAVAILABLE,
    }


def _percentile(sorted_values: list[int], percentile: int) -> int:
    """Return the nearest-rank percentile from an already sorted list."""
    if not sorted_values:
        return 0
    rank = (len(sorted_values) * percentile + 99) // 100
    return sorted_values[max(0, rank - 1)]


def _run_round(total_work: int, worker_count: int, round_number: int, capacity: int) -> dict[str, Any]:
    """Run one bounded-queue round while preserving the fixed work total."""
    work_queue: queue.Queue[tuple[int, int]] = queue.Queue(maxsize=capacity)
    dispatch_lock = threading.Lock()
    next_work = 0
    admission_latencies: list[int] = []
    admission_lock = threading.Lock()
    queue_wait_ns = 0
    queue_wait_lock = threading.Lock()
    rejected = 0
    rejected_lock = threading.Lock()
    errors = 0
    errors_lock = threading.Lock()

    def worker() -> None:
        """Submit a disjoint portion of the fixed work into the queue."""
        nonlocal next_work, rejected, errors
        try:
            while True:
                with dispatch_lock:
                    work_index = next_work
                    next_work += 1
                if work_index >= total_work:
                    return
                admission_started = time.perf_counter_ns()
                while True:
                    try:
                        work_queue.put_nowait((work_index, work_index))
                        break
                    except queue.Full:
                        with rejected_lock:
                            rejected += 1
                        time.sleep(0)
                admission_ns = max(1, time.perf_counter_ns() - admission_started)
                with admission_lock:
                    admission_latencies.append(admission_ns)
        except Exception:
            with errors_lock:
                errors += 1

    resources_before = _resource_snapshot()
    started = time.perf_counter_ns()
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(worker_count)]
    for thread in threads:
        thread.start()

    completed = 0
    while completed < total_work:
        pop_started = time.perf_counter_ns()
        try:
            work_queue.get_nowait()
        except queue.Empty:
            with queue_wait_lock:
                queue_wait_ns += max(0, time.perf_counter_ns() - pop_started)
            time.sleep(0)
        else:
            completed += 1
            work_queue.task_done()

    for thread in threads:
        thread.join()
    elapsed_ns = max(1, time.perf_counter_ns() - started)
    resources_after = _resource_snapshot()
    admission_latencies.sort()
    if len(admission_latencies) != total_work or next_work < total_work:
        raise RuntimeError("reference benchmark did not submit the fixed work total")
    if not work_queue.empty():
        raise RuntimeError("reference benchmark queue did not drain")
    resources = _resource_delta(resources_before, resources_after)
    return {
        "workers": worker_count,
        "round": round_number,
        "completed_work_items": completed,
        "elapsed_ns": elapsed_ns,
        "p95_latency_ns": _percentile(admission_latencies, 95),
        "p99_latency_ns": _percentile(admission_latencies, 99),
        "queue_wait_ns": queue_wait_ns,
        "lock_wait_ns": sum(admission_latencies),
        "rejected": rejected,
        "errors": errors,
        "resources": resources,
    }


def build_evidence(
    *,
    workload: str = DEFAULT_WORKLOAD,
    total_work: int = DEFAULT_TOTAL_WORK,
    workers: tuple[int, ...] = DEFAULT_WORKERS,
    rounds: int = DEFAULT_ROUNDS,
    capacity: int = DEFAULT_CAPACITY,
) -> dict[str, Any]:
    """Build a validated Python evidence envelope for the fixed workload."""
    if not workload or total_work < 1 or not workers or any(worker < 1 for worker in workers):
        raise ValueError("workload, total work, and workers must be positive")
    if len(set(workers)) != len(workers) or rounds < 1 or capacity < 1:
        raise ValueError("workers must be unique and rounds/capacity must be positive")
    samples = [
        _run_round(total_work, worker_count, round_number, capacity)
        for worker_count in workers
        for round_number in range(rounds)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "platform": sys.platform,
            "architecture": platform.machine() or "unknown",
            "runtime": f"python-{platform.python_version()}",
            "git_revision": _git_revision(),
            "runner": "python-r2-reference/1",
            "resource_sampling": {
                "cpu_unit": CPU_TIME_UNIT,
                "memory_unit": MEMORY_UNIT,
                "scope": RESOURCE_SCOPE,
            },
        },
        "report": {
            "schema_version": SCHEMA_VERSION,
            "spec": {
                "schema_version": SCHEMA_VERSION,
                "workload": workload,
                "total_work_items": total_work,
                "workers": list(workers),
                "rounds": rounds,
            },
            "samples": samples,
        },
    }


def main() -> int:
    """Parse options and emit one machine-readable evidence document."""
    parser = argparse.ArgumentParser(description="Run the Python R2 fixed-work reference")
    parser.add_argument("--output", type=Path, default=None, help="also write evidence JSON to this path")
    parser.add_argument("--total-work", type=int, default=DEFAULT_TOTAL_WORK)
    parser.add_argument("--capacity", type=int, default=DEFAULT_CAPACITY)
    args = parser.parse_args()
    evidence = build_evidence(total_work=args.total_work, capacity=args.capacity)
    document = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
    print(document, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
