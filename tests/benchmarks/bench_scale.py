"""Benchmark: kernel scaling curve + hard metrics for the Rust migration.

Measures how Praxis's kernel scales and where its hard costs are, so a
Rust rewrite knows what to optimize first. Two families of evidence:

1. Amdahl scaling curves (serial fraction P):
   - fixed-total L1 scheduler + Mutex + RingChannel work set
   - each worker count receives the same number of work items in aggregate
   - reports throughput, operation latency, scheduler queue wait, and lock wait
   High P in this real kernel path ⇒ a Rust port should investigate the
   scheduler and shared-lock implementation. Results are evidence only after
   this benchmark has completed on the target platform.

2. Hard metrics (per-primitive cost and contention):
   - lock contention curve (Mutex/RWLock ops/sec vs worker count)
   - locked vs lock-free comparison
   - scheduling latency (submit→execute p50/p95)
   - RingChannel + event-bus throughput
   - Constitution.check() evaluation cost (analysis module)
   - allocator alloc/free + memory reclamation cost

Standalone (no L3 boot) like bench_platform.py. Run per platform and diff
the JSON outputs to build a pre/post-migration baseline.

Usage:
    python tests/benchmarks/bench_scale.py                 # all metrics
    python tests/benchmarks/bench_scale.py --mode amdahl   # Amdahl only
    python tests/benchmarks/bench_scale.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from l4.params import (
    EVAL_ALLOC_SHARD_WORKERS,
    EVAL_AMDAHL_AGENTS,
    EVAL_AMDAHL_LATENCY_PERCENTILES,
    EVAL_AMDAHL_RING_CAPACITY,
    EVAL_AMDAHL_ROUNDS,
    EVAL_AMDAHL_TASK_TIMEOUT,
    EVAL_AMDAHL_TOTAL_WORK_ITEMS,
    EVAL_CONSTITUTION_ITERS,
    EVAL_DIFF_COMPRESS_ITERS,
    EVAL_DIFF_HEADER_ITERS,
    EVAL_DIFF_HUNK_ITERS,
    EVAL_EVENT_BOUNDED_ITERS,
    EVAL_EVENT_ITERS,
    EVAL_EVENT_LISTENERS,
    EVAL_GATECHAIN_ITERS,
    EVAL_INTERRUPT_ITERS,
    EVAL_IPC_ITERS,
    EVAL_IPC_RTT_ITERS,
    EVAL_JSON_PARSE_ITERS,
    EVAL_JSON_PAYLOAD_BYTES,
    EVAL_LOCK_CONTEND_TOTAL_OPS,
    EVAL_LOCK_CONTEND_WORKERS,
    EVAL_LOCKFREE_ITERS,
    EVAL_MEMORY_ALLOC_ITERS,
    EVAL_PERSIST_ITERS,
    EVAL_PRESSURE_AGENTS,
    EVAL_PROCESS_ITERS,
    EVAL_QUEUE_ITERS,
    EVAL_RECLAIM_ITERS,
    EVAL_REPUTATION_ITERS,
    EVAL_RESOURCE_ITERS,
    EVAL_SATURATION_DELTA,
    EVAL_SCHED_LATENCY_TASKS,
    EVAL_SERIAL_P_THRESHOLD,
    EVAL_SKILL_ITERS,
    EVAL_SWAP_ITERS,
    EVAL_SYNC_ITERS,
    EVAL_TERRITORY_ITERS,
    EVAL_VFS_ITERS,
)

# ── Shared helpers ─────────────────────────────────────────────────────────


def _median(values: list[float]) -> float:
    """Return the median of *values*."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _measure(fn: Callable[[], float], rounds: int) -> float:
    """Run *fn* (returns a wall time) for *rounds* passes; return median."""
    return _median([fn() for _ in range(rounds)])


def _ops_per_sec(ops: int, wall: float) -> float:
    """Return ops/sec for *ops* operations over *wall* seconds."""
    return ops / wall if wall > 0 else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    """Return the nearest-rank percentile from a non-empty latency sample."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(math.ceil(len(ordered) * percentile) - 1, len(ordered) - 1)
    return ordered[index]


def _split_fixed_work(total_work_items: int, workers: int) -> list[int]:
    """Split one fixed work set across workers while preserving its exact total."""
    if total_work_items < workers or workers < 1:
        raise ValueError("work items must be at least the positive worker count")
    base, remainder = divmod(total_work_items, workers)
    return [base + int(worker_index < remainder) for worker_index in range(workers)]


def _fit_serial_fraction(agent_counts: list[int], wall_times: list[float]) -> float:
    """Fit the Amdahl serial fraction P by least squares on T(N)/T(1) vs 1/N.

    Amdahl: T(N) = T(1) * (P + (1-P)/N), so y = T(N)/T(1) vs x = 1/N is a
    line with intercept P and slope 1-P. Least squares over all points is
    robust to noise.
    """
    t1 = wall_times[0]
    if t1 <= 0:
        return 0.0
    xs = [1.0 / n for n in agent_counts]
    ys = [t / t1 for t in wall_times]
    n = len(xs)
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    cov = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys, strict=True))
    var = sum((x - xbar) ** 2 for x in xs)
    if var == 0:
        return 0.0
    parallel_fraction = cov / var
    p = 1.0 - parallel_fraction
    return max(0.0, min(1.0, p))


def _amdahl_speedup(p: float, n: int) -> float:
    """Amdahl predicted speedup for serial fraction *p* at *n* workers."""
    return 1.0 / (p + (1.0 - p) / n)


def _sweep_report(
    agent_counts: list[int],
    wall_times: list[float],
    total_work_items: int,
    measurements: list[dict[str, float]],
) -> dict[str, Any]:
    """Build the Amdahl report dict (serial fraction, speedups, verdict)."""
    p = _fit_serial_fraction(agent_counts, wall_times)
    t1 = wall_times[0]
    measured = [t1 / t if t > 0 else 0.0 for t in wall_times]
    theoretical = [_amdahl_speedup(p, n) for n in agent_counts]
    saturation_gain = 0.0
    if len(measured) >= 2 and measured[-2] > 0:
        saturation_gain = (measured[-1] - measured[-2]) / measured[-2]
    saturated = saturation_gain < EVAL_SATURATION_DELTA
    return {
        "agent_counts": agent_counts,
        "fixed_total_work_items": total_work_items,
        "completed_work_items": [int(sample["completed_work_items"]) for sample in measurements],
        "wall_times": [round(t, 4) for t in wall_times],
        "throughput_ops_per_sec": [round(_ops_per_sec(total_work_items, t), 0) for t in wall_times],
        "operation_latency_p50_ms": [round(sample["operation_latency_p50_ms"], 4) for sample in measurements],
        "operation_latency_p95_ms": [round(sample["operation_latency_p95_ms"], 4) for sample in measurements],
        "queue_wait_p50_ms": [round(sample["queue_wait_p50_ms"], 4) for sample in measurements],
        "queue_wait_p95_ms": [round(sample["queue_wait_p95_ms"], 4) for sample in measurements],
        "lock_wait_p50_ms": [round(sample["lock_wait_p50_ms"], 4) for sample in measurements],
        "lock_wait_p95_ms": [round(sample["lock_wait_p95_ms"], 4) for sample in measurements],
        "measured_speedups": [round(s, 3) for s in measured],
        "theoretical_speedups": [round(s, 3) for s in theoretical],
        "serial_fraction_p": round(p, 4),
        "serial_p_threshold": EVAL_SERIAL_P_THRESHOLD,
        "saturation_gain_last_step": round(saturation_gain, 4),
        "saturated": saturated,
        "verdict": _verdict(p, saturated),
    }


def _verdict(p: float, saturated: bool) -> str:
    """Human-readable Rust-migration recommendation."""
    high_p = p >= EVAL_SERIAL_P_THRESHOLD
    if high_p and saturated:
        return "high serial + saturated: profile scheduler and shared locks before choosing a Rust target"
    if high_p:
        return "high serial fraction: profile scheduler and shared locks before choosing a Rust target"
    if saturated:
        return "low serial + saturated: latency dominates; Rust kernel benefit limited"
    return "low serial fraction: bottleneck outside kernel compute; Rust benefit modest"


def collect_platform_info() -> dict[str, Any]:
    """Return a dict describing the host OS, Python, and CPU."""
    info: dict[str, Any] = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
        "pid": os.getpid(),
    }
    if platform.system() == "Linux":
        try:
            with open("/proc/version", encoding="utf-8", errors="replace") as f:
                ver = f.read().lower()
            info["wsl"] = "microsoft" in ver or "wsl" in ver
        except OSError:
            info["wsl"] = False
    return info


# ── Amdahl: fixed-total L1 scheduler + shared synchronization path ─────────


def _amdahl_agent_work(
    agent_id: str,
    work_items: int,
    start_barrier: threading.Barrier,
    mutex: Any,
    channel: Any,
    benchmark_start: float,
) -> dict[str, Any]:
    """Execute one agent's L1 work partition and return latency samples.

    The shared Mutex models a kernel coordination point and protects a
    RingChannel round trip. Each worker has its own identity, so mutex
    reentrancy cannot accidentally turn this into a same-agent benchmark.
    """
    queue_wait_s = time.perf_counter() - benchmark_start
    start_barrier.wait(timeout=EVAL_AMDAHL_TASK_TIMEOUT)
    operation_latencies_s: list[float] = []
    lock_waits_s: list[float] = []
    for work_index in range(work_items):
        operation_start = time.perf_counter()
        lock_start = operation_start
        acquired = mutex.acquire(agent_id, blocking=True)
        lock_waits_s.append(time.perf_counter() - lock_start)
        if not acquired["success"]:
            raise RuntimeError("Amdahl mutex acquire failed")
        try:
            if not channel.put((agent_id, work_index)):
                raise RuntimeError("Amdahl RingChannel put failed")
            if channel.get() is None:
                raise RuntimeError("Amdahl RingChannel get failed")
        finally:
            released = mutex.release(agent_id)
            if not released["success"]:
                raise RuntimeError("Amdahl mutex release failed")
        operation_latencies_s.append(time.perf_counter() - operation_start)
    return {
        "completed_work_items": work_items,
        "operation_latencies_s": operation_latencies_s,
        "queue_wait_s": queue_wait_s,
        "lock_waits_s": lock_waits_s,
    }


def _amdahl_l1_round(workers: int, total_work_items: int) -> dict[str, float]:
    """Run one fixed-total L1 scheduler and synchronization measurement round."""
    from l1.kernel.channel_ring import RingChannel
    from l1.kernel.sync import Mutex
    from l1.kernel.worker_thread import ThreadPoolWorker

    work_partitions = _split_fixed_work(total_work_items, workers)
    mutex = Mutex(f"bench_amdahl_mutex_{workers}")
    channel = RingChannel(capacity=EVAL_AMDAHL_RING_CAPACITY)
    start_barrier = threading.Barrier(workers)
    pool = ThreadPoolWorker(min_workers=workers, max_workers=workers, queue_size=workers)
    benchmark_start = time.perf_counter()
    try:
        handles = [
            pool.submit_result(
                _amdahl_agent_work,
                f"amdahl-agent-{agent_index}",
                work_items,
                start_barrier,
                mutex,
                channel,
                benchmark_start,
            )
            for agent_index, work_items in enumerate(work_partitions)
        ]
        results = [handle.result(timeout=EVAL_AMDAHL_TASK_TIMEOUT) for handle in handles]
        wall_s = time.perf_counter() - benchmark_start
    finally:
        pool.shutdown(wait=True, timeout=EVAL_AMDAHL_TASK_TIMEOUT)

    operation_latencies_s = [latency for result in results for latency in result["operation_latencies_s"]]
    lock_waits_s = [wait for result in results for wait in result["lock_waits_s"]]
    queue_waits_s = [result["queue_wait_s"] for result in results]
    p50, p95 = EVAL_AMDAHL_LATENCY_PERCENTILES
    return {
        "wall_s": wall_s,
        "completed_work_items": float(sum(result["completed_work_items"] for result in results)),
        "operation_latency_p50_ms": _percentile(operation_latencies_s, p50) * 1_000,
        "operation_latency_p95_ms": _percentile(operation_latencies_s, p95) * 1_000,
        "queue_wait_p50_ms": _percentile(queue_waits_s, p50) * 1_000,
        "queue_wait_p95_ms": _percentile(queue_waits_s, p95) * 1_000,
        "lock_wait_p50_ms": _percentile(lock_waits_s, p50) * 1_000,
        "lock_wait_p95_ms": _percentile(lock_waits_s, p95) * 1_000,
    }


def run_amdahl_l1(agent_counts: list[int], total_work_items: int, rounds: int) -> dict[str, Any]:
    """Measure a fixed-total L1 scheduler, Mutex, and RingChannel workload."""
    wall_times: list[float] = []
    measurements: list[dict[str, float]] = []
    for workers in agent_counts:
        samples = [_amdahl_l1_round(workers, total_work_items) for _ in range(rounds)]
        wall_times.append(_median([sample["wall_s"] for sample in samples]))
        measurements.append(
            {key: _median([sample[key] for sample in samples]) for key in samples[0] if key != "wall_s"}
        )
    return _sweep_report(agent_counts, wall_times, total_work_items, measurements)


# ── Lock contention curve ──────────────────────────────────────────────────


def _contended_mutex_ops(workers: int, total_work_items: int) -> dict[str, Any]:
    """Run fixed-total Mutex contention with a distinct agent identity per worker."""
    from l1.kernel.sync import Mutex

    m = Mutex("bench_contended")
    barrier = threading.Barrier(workers)
    work_partitions = _split_fixed_work(total_work_items, workers)
    worker_waits: list[list[float]] = [[] for _ in range(workers)]
    worker_errors: list[Exception] = []

    def _worker(worker_index: int, work_items: int) -> None:
        try:
            agent_id = f"lock-bench-agent-{worker_index}"
            barrier.wait()
            waits = worker_waits[worker_index]
            for _ in range(work_items):
                lock_start = time.perf_counter()
                acquired = m.acquire(agent_id, blocking=True)
                waits.append(time.perf_counter() - lock_start)
                if not acquired["success"]:
                    raise RuntimeError("contended Mutex acquire failed")
                released = m.release(agent_id)
                if not released["success"]:
                    raise RuntimeError("contended Mutex release failed")
        except Exception as exc:
            worker_errors.append(exc)

    threads = [
        threading.Thread(target=_worker, args=(worker_index, work_items), daemon=True)
        for worker_index, work_items in enumerate(work_partitions)
    ]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if worker_errors:
        raise worker_errors[0]
    return {
        "wall_s": time.perf_counter() - start,
        "completed_work_items": total_work_items,
        "lock_waits_s": [wait for waits in worker_waits for wait in waits],
    }


def _contended_rwlock_ops(workers: int, total_work_items: int) -> dict[str, Any]:
    """Run fixed-total RWLock contention with a distinct agent identity per worker."""
    from l1.kernel.sync import RWLock

    rw = RWLock("bench_rw_contended")
    barrier = threading.Barrier(workers)
    work_partitions = _split_fixed_work(total_work_items, workers)
    worker_waits: list[list[float]] = [[] for _ in range(workers)]
    worker_errors: list[Exception] = []

    def _worker(worker_index: int, work_items: int) -> None:
        try:
            agent_id = f"rwlock-bench-agent-{worker_index}"
            barrier.wait()
            waits = worker_waits[worker_index]
            for _ in range(work_items):
                lock_start = time.perf_counter()
                acquired = rw.read_lock(agent_id)
                waits.append(time.perf_counter() - lock_start)
                if not acquired["success"]:
                    raise RuntimeError("contended RWLock acquire failed")
                released = rw.unlock(agent_id)
                if not released["success"]:
                    raise RuntimeError("contended RWLock release failed")
        except Exception as exc:
            worker_errors.append(exc)

    threads = [
        threading.Thread(target=_worker, args=(worker_index, work_items), daemon=True)
        for worker_index, work_items in enumerate(work_partitions)
    ]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if worker_errors:
        raise worker_errors[0]
    return {
        "wall_s": time.perf_counter() - start,
        "completed_work_items": total_work_items,
        "lock_waits_s": [wait for waits in worker_waits for wait in waits],
    }


def _contention_metrics(
    operation: Callable[[int, int], dict[str, Any]], workers: int, total_work_items: int, rounds: int
) -> dict[str, float]:
    """Return median throughput and lock-wait measurements for one lock curve point."""
    samples = [operation(workers, total_work_items) for _ in range(rounds)]
    p50, p95 = EVAL_AMDAHL_LATENCY_PERCENTILES
    walls = [sample["wall_s"] for sample in samples]
    return {
        "wall_s": _median(walls),
        "completed_work_items": float(total_work_items),
        "lock_wait_p50_ms": _median([_percentile(sample["lock_waits_s"], p50) * 1_000 for sample in samples]),
        "lock_wait_p95_ms": _median([_percentile(sample["lock_waits_s"], p95) * 1_000 for sample in samples]),
    }


def run_lock_contention(workers_list: list[int], total_work_items: int, rounds: int) -> dict[str, Any]:
    """Measure fixed-total Mutex and RWLock contention versus worker count."""
    mutex_curve: dict[str, Any] = {}
    rwlock_curve: dict[str, Any] = {}
    mutex_single = _contention_metrics(_contended_mutex_ops, 1, total_work_items, rounds)
    rwlock_single = _contention_metrics(_contended_rwlock_ops, 1, total_work_items, rounds)
    for n in workers_list:
        mutex_metrics = _contention_metrics(_contended_mutex_ops, n, total_work_items, rounds)
        mutex_speedup = mutex_single["wall_s"] / mutex_metrics["wall_s"] if mutex_metrics["wall_s"] else 0.0
        mutex_curve[str(n)] = {
            "fixed_total_work_items": int(mutex_metrics["completed_work_items"]),
            "ops_per_sec": round(_ops_per_sec(total_work_items, mutex_metrics["wall_s"]), 0),
            "speedup_vs_single": round(mutex_speedup, 3),
            "parallel_efficiency": round(mutex_speedup / n, 3),
            "lock_wait_p50_ms": round(mutex_metrics["lock_wait_p50_ms"], 4),
            "lock_wait_p95_ms": round(mutex_metrics["lock_wait_p95_ms"], 4),
        }
        rwlock_metrics = _contention_metrics(_contended_rwlock_ops, n, total_work_items, rounds)
        rwlock_speedup = rwlock_single["wall_s"] / rwlock_metrics["wall_s"] if rwlock_metrics["wall_s"] else 0.0
        rwlock_curve[str(n)] = {
            "fixed_total_work_items": int(rwlock_metrics["completed_work_items"]),
            "ops_per_sec": round(_ops_per_sec(total_work_items, rwlock_metrics["wall_s"]), 0),
            "speedup_vs_single": round(rwlock_speedup, 3),
            "parallel_efficiency": round(rwlock_speedup / n, 3),
            "lock_wait_p50_ms": round(rwlock_metrics["lock_wait_p50_ms"], 4),
            "lock_wait_p95_ms": round(rwlock_metrics["lock_wait_p95_ms"], 4),
        }
    return {"mutex": mutex_curve, "rwlock": rwlock_curve}


# ── Locked vs lock-free ────────────────────────────────────────────────────


def _locked_increment(iters: int) -> float:
    """N threads increment a shared int under a lock; return wall (s)."""
    lock = threading.Lock()
    counter = [0]

    def _worker() -> None:
        for _ in range(iters):
            with lock:
                counter[0] += 1

    threads = [threading.Thread(target=_worker, daemon=True) for _ in range(4)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return time.perf_counter() - start


def _lockfree_increment(iters: int) -> float:
    """4 threads increment a shared counter with a lock-free sharded merge.

    Each worker accumulates locally (no shared-write contention) and merges
    once at the end — the lock-free baseline to contrast against per-op
    locking.
    """
    shards = [0] * 16
    lock = threading.Lock()

    def _worker() -> None:
        local = 0
        for _ in range(iters):
            local += 1
        with lock:
            shards[0] += local  # merge once per worker, not per-op

    threads = [threading.Thread(target=_worker, daemon=True) for _ in range(4)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return time.perf_counter() - start


def run_lock_vs_lockfree(iters: int, rounds: int) -> dict[str, Any]:
    """Compare 4-thread locked increment against a lock-free sharded one."""
    locked_wall = _measure(lambda: _locked_increment(iters), rounds)
    lockfree_wall = _measure(lambda: _lockfree_increment(iters), rounds)
    locked_ops = _ops_per_sec(4 * iters, locked_wall)
    lockfree_ops = _ops_per_sec(4 * iters, lockfree_wall)
    return {
        "locked_ops_per_sec": round(locked_ops, 0),
        "lockfree_ops_per_sec": round(lockfree_ops, 0),
        "lock_overhead_ratio": round(locked_ops / lockfree_ops if lockfree_ops else 0.0, 3),
    }


# ── Scheduling latency ─────────────────────────────────────────────────────


def run_scheduling_latency(tasks: int) -> dict[str, Any]:
    """Worker-pool submit→execute latency distribution (p50/p95)."""
    from l1.kernel.worker_thread import ThreadPoolWorker

    pool = ThreadPoolWorker(min_workers=2, max_workers=8, queue_size=8192)
    latencies: list[float] = [0.0] * tasks
    _start = time.perf_counter()

    def _task(i: int) -> None:
        # Record submit→execute latency directly; the task returns immediately
        # so workers never block and keep draining the queue.
        latencies[i] = time.perf_counter() - _start

    try:
        for i in range(tasks):
            pool.submit(_task, i)
        # All tasks submitted; wait for the queue to drain.
        deadline = time.time() + 15.0
        while pool.stats()["queued"] > 0 and time.time() < deadline:
            time.sleep(0.01)
    finally:
        pool.shutdown(wait=True)

    ordered = sorted(latencies) if latencies else [0.0]
    n = len(ordered)
    p50 = ordered[int(n * 0.50)] if n else 0.0
    p95 = ordered[int(n * 0.95)] if n else 0.0
    return {
        "tasks": n,
        "p50_ms": round(p50 * 1000, 4),
        "p95_ms": round(p95 * 1000, 4),
        "max_ms": round((ordered[-1] if ordered else 0.0) * 1000, 4),
    }


# ── Queue + event-bus throughput ───────────────────────────────────────────


def _queue_wall(iters: int) -> float:
    """Single-thread RingChannel put+get round trips; return wall (s)."""
    from l1.kernel.channel_ring import RingChannel

    ch = RingChannel(capacity=1024)
    start = time.perf_counter()
    for _ in range(iters):
        ch.put(1)
        ch.get(timeout=0.001)
    return time.perf_counter() - start


def _event_round(iters: int, listeners: int) -> dict[str, Any]:
    """Measure one isolated EventBus emit round and drain its callbacks."""
    from l1.kernel.event import EventBus
    from l1.kernel.params.kernel import EVENT_BUS_SHUTDOWN_TIMEOUT

    bus = EventBus()
    callbacks: list[Callable] = []
    wall_s = 0.0
    try:
        for _ in range(listeners):

            def callback(_event: Any) -> None:
                return None

            callbacks.append(callback)
            bus.on_any(callback)
        start = time.perf_counter()
        for _ in range(iters):
            bus.emit_event("bench.marker", {"i": 0})
        wall_s = time.perf_counter() - start
    finally:
        for callback in callbacks:
            bus.off_any(callback)
        bus.shutdown(wait=True, timeout=EVENT_BUS_SHUTDOWN_TIMEOUT)
    stats = bus.stats()
    dispatch_attempts = stats["submitted"] + stats["dropped"]
    drained = stats["queue_depth"] == 0
    return {
        "wall_s": wall_s,
        "submitted": stats["submitted"],
        "completed": stats["completed"],
        "dropped": stats["dropped"],
        "queue_depth": stats["queue_depth"],
        "drop_rate": stats["dropped"] / dispatch_attempts if dispatch_attempts else 0.0,
        "drained": drained,
        "clean": stats["dropped"] == 0 and drained,
    }


def _event_wall(iters: int, listeners: int) -> float:
    """Event-bus emit with *listeners* subscribers; return wall (s)."""
    return float(_event_round(iters, listeners)["wall_s"])


def _event_report(iters: int, samples: list[dict[str, Any]], baseline_wall: float) -> dict[str, Any]:
    """Summarize EventBus rounds while preserving per-round delivery evidence."""
    wall = _median([float(sample["wall_s"]) for sample in samples])
    submitted = sum(int(sample["submitted"]) for sample in samples)
    completed = sum(int(sample["completed"]) for sample in samples)
    dropped = sum(int(sample["dropped"]) for sample in samples)
    dispatch_attempts = submitted + dropped
    return {
        "ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "wall_s": round(wall, 6),
        "degradation_vs_zero": round((baseline_wall / wall) if wall > 0 else 0.0, 3),
        "submitted": submitted,
        "completed": completed,
        "dropped": dropped,
        "queue_depth": max(int(sample["queue_depth"]) for sample in samples),
        "drop_rate": round(dropped / dispatch_attempts if dispatch_attempts else 0.0, 6),
        "drained": all(bool(sample["drained"]) for sample in samples),
        "clean": all(bool(sample["clean"]) for sample in samples),
        "rounds": samples,
    }


def _event_curve(event_iters: int, listener_counts: list[int], rounds: int) -> dict[str, Any]:
    """Measure one EventBus load curve and compare it with a zero-listener baseline."""
    event: dict[str, Any] = {}
    zero_samples = [_event_round(event_iters, 0) for _ in range(rounds)]
    zero_wall = _median([float(sample["wall_s"]) for sample in zero_samples])
    for n in listener_counts:
        samples = [_event_round(event_iters, n) for _ in range(rounds)]
        event[str(n)] = _event_report(event_iters, samples, zero_wall)
    if "0" in event:
        event["0"] = _event_report(event_iters, zero_samples, zero_wall)
    return event


def run_queue_event(
    queue_iters: int,
    event_iters: int,
    listener_counts: list[int],
    rounds: int,
    bounded_event_iters: int | None = None,
) -> dict[str, Any]:
    """RingChannel throughput plus normal and optional bounded EventBus curves."""
    queue_wall = _measure(lambda: _queue_wall(queue_iters), rounds)
    event = _event_curve(event_iters, listener_counts, rounds)
    report = {
        "queue_put_get_ops_per_sec": round(_ops_per_sec(queue_iters, queue_wall), 0),
        "event_bus": event,
    }
    if bounded_event_iters is not None:
        report["bounded_event_bus"] = _event_curve(bounded_event_iters, listener_counts, rounds)
    return report


# ── Constitution analysis module ───────────────────────────────────────────


def _constitution_wall(iters: int) -> float:
    """Constitution.check() evaluation cost for a realistic action."""
    from l1.kernel.constitution import get_constitution

    c = get_constitution()
    start = time.perf_counter()
    for _ in range(iters):
        c.check("read_file", "agent_a", target="/project/foo.py", territory=["/project"])
    return time.perf_counter() - start


def run_constitution(iters: int, rounds: int) -> dict[str, Any]:
    """Constitution rule-evaluation throughput + per-check cost."""
    wall = _measure(lambda: _constitution_wall(iters), rounds)
    return {
        "checks_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_check": round(wall / iters * 1_000_000, 3),
        "rules_evaluated_per_check": _rules_per_check(),
    }


def _rules_per_check() -> int:
    """Number of rules the pre-filtered check() actually evaluates."""
    from l1.kernel.constitution import get_constitution

    return len(get_constitution()._relevant_rules("read_file"))


# ── Memory: allocator + reclamation ────────────────────────────────────────


def _alloc_wall(iters: int) -> float:
    """Allocator alloc+free round trips for one agent; return wall (s)."""
    from l1.kernel.allocator import get_allocator

    a = get_allocator()
    start = time.perf_counter()
    for _ in range(iters):
        a.alloc("bench_agent", "tokens", 1, "bench")
        a.free("bench_agent", "tokens", 1)
    return time.perf_counter() - start


def _reclaim_wall(iters: int) -> float:
    """Allocator cleanup_agent (reclamation/GC) cost; return wall (s).

    Each iteration registers a fresh agent, allocates, then immediately drops
    it via cleanup_agent — so no agent's usage accumulates across iterations
    and the allocator never escalates into an OOM kill (which would dominate
    the measurement with process-exit side effects).
    """
    from l1.kernel.allocator import get_allocator

    a = get_allocator()
    start = time.perf_counter()
    for i in range(iters):
        agent = f"gc_{i}"
        a.alloc(agent, "tokens", 10, "bench")
        a.alloc(agent, "ring1", 5, "bench")
        a.cleanup_agent(agent)
    return time.perf_counter() - start


def run_memory(alloc_iters: int, rounds: int) -> dict[str, Any]:
    """Allocator alloc/free throughput + cleanup_agent reclamation cost."""
    alloc_wall = _measure(lambda: _alloc_wall(alloc_iters), rounds)
    reclaim_wall = _measure(lambda: _reclaim_wall(alloc_iters), rounds)
    return {
        "alloc_free_ops_per_sec": round(_ops_per_sec(alloc_iters, alloc_wall), 0),
        "us_per_alloc_free": round(alloc_wall / alloc_iters * 1_000_000, 3),
        "reclaim_ops_per_sec": round(_ops_per_sec(alloc_iters, reclaim_wall), 0),
        "us_per_reclaim_call": round(reclaim_wall / alloc_iters * 1_000_000, 3),
    }


# ── GateChain analysis module ──────────────────────────────────────────────


def _gatechain_wall(iters: int) -> float:
    """GateChain.check() cost for a passing low-danger tool call (G1-G5)."""
    from l1.kernel.gatechain import get_gatechain

    gc = get_gatechain()
    gc.register_tools(["read_file"])
    gc.set_territories({"agent_a": ["/project"]})
    start = time.perf_counter()
    for _ in range(iters):
        gc.check("read_file", "agent_a", target="/project/foo.py", territory=["/project"])
    return time.perf_counter() - start


def run_gatechain(iters: int, rounds: int) -> dict[str, Any]:
    """GateChain G1-G5 rule-analysis throughput + per-check cost."""
    wall = _measure(lambda: _gatechain_wall(iters), rounds)
    return {
        "checks_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_check": round(wall / iters * 1_000_000, 3),
    }


# ── Memory reclamation: pressure / swap_out / TTL reclaim ──────────────────


def _pressure_wall(iters: int, agents: int) -> float:
    """pressure() O(N) cross-agent scan cost at *agents* scale.

    Creates a fresh set of agent allocations *every iteration* so OOM pressure
    does not accumulate across iterations.
    """
    from l1.kernel.allocator import get_allocator

    a = get_allocator()
    start = time.perf_counter()
    for _ in range(iters):
        for i in range(agents):
            a.alloc(f"pressure_{i}", "tokens", 10, "bench")
        a.pressure()
        for i in range(agents):
            a.cleanup_agent(f"pressure_{i}")
    return time.perf_counter() - start


def _swap_wall(iters: int) -> float:
    """swap_out() ring2→ring3 move cost; return wall (s).

    Each iteration allocates one ring2 token then swaps it to ring3, so the
    agent's usage stays bounded and no OOM escalation can build up.
    """
    from l1.kernel.allocator import get_allocator
    from l1.kernel.params import allocator as _alloc_params

    a = get_allocator()
    src = _alloc_params.ALLOCATOR_SWAP_SOURCE
    tgt = _alloc_params.ALLOCATOR_SWAP_TARGET
    a.cleanup_agent("swap_agent")
    start = time.perf_counter()
    for _ in range(iters):
        a.alloc("swap_agent", src, 1, "bench")
        a.swap_out("swap_agent", src, tgt, count=1)
    return time.perf_counter() - start


def run_memory_reclaim(reclaim_iters: int, swap_iters: int, agents: int, rounds: int) -> dict[str, Any]:
    """Allocator pressure() scan + swap_out eviction cost."""
    pressure_wall = _measure(lambda: _pressure_wall(reclaim_iters, agents), rounds)
    swap_wall = _measure(lambda: _swap_wall(swap_iters), rounds)
    return {
        "pressure_scan_ops_per_sec": round(_ops_per_sec(reclaim_iters, pressure_wall), 0),
        "pressure_agents": agents,
        "swap_out_ops_per_sec": round(_ops_per_sec(swap_iters, swap_wall), 0),
        "us_per_swap_out": round(swap_wall / swap_iters * 1_000_000, 3),
    }


# ── Allocator shard contention curve ───────────────────────────────────────


def _shard_alloc_ops(workers: int, iters: int) -> float:
    """*workers* threads alloc+free on distinct agents (shard parallelism)."""
    from l1.kernel.allocator import get_allocator

    a = get_allocator()
    barrier = threading.Barrier(workers)

    def _worker(wid: int) -> None:
        agent = f"shard_{wid}"
        barrier.wait()
        for _ in range(iters):
            a.alloc(agent, "tokens", 1, "bench")
            a.free(agent, "tokens", 1)

    threads = [threading.Thread(target=_worker, args=(w,), daemon=True) for w in range(workers)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return time.perf_counter() - start


def run_alloc_shards(workers_list: list[int], iters: int, rounds: int) -> dict[str, Any]:
    """Allocator throughput vs worker count (per-agent shard locking)."""
    single = _measure(lambda: _shard_alloc_ops(1, iters), rounds)
    curve: dict[str, Any] = {}
    for n in workers_list:
        wall = _measure(lambda _n=n: _shard_alloc_ops(_n, iters), rounds)
        curve[str(n)] = {
            "ops_per_sec": round(_ops_per_sec(n * iters, wall), 0),
            "efficiency_vs_single": round((single / wall) if wall > 0 else 0.0, 3),
        }
    return curve


# ── Sync primitives: Semaphore / Barrier ───────────────────────────────────


def _semaphore_wall(iters: int) -> float:
    """Uncontended Semaphore acquire/release round trips (single thread)."""
    from l1.kernel.sync import Semaphore

    s = Semaphore("bench_sem", max_count=1024)
    start = time.perf_counter()
    for _ in range(iters):
        s.acquire("agent_a", blocking=True)
        s.release("agent_a")
    return time.perf_counter() - start


def _barrier_wall(iters: int) -> float:
    """Barrier round trips: two threads rendezvous on a 2-party barrier.

    Each round both parties wait() and the last arriver releases them, so the
    barrier.wait() path is exercised once per thread per round in parallel.
    """
    from l1.kernel.sync import Barrier

    b = Barrier("bench_barr", count=2)  # 2 distinct parties x 2 threads
    done = threading.Barrier(3)

    def _worker(tag: str) -> None:
        for _ in range(iters):
            b.wait(tag)
        done.wait()  # signal completion (main + 2 workers)

    start = time.perf_counter()
    threads = [threading.Thread(target=_worker, args=("a",), daemon=True)]
    threads.append(threading.Thread(target=_worker, args=("b",), daemon=True))
    for t in threads:
        t.start()
    done.wait()  # wait for both workers to finish
    for t in threads:
        t.join(timeout=10)
    return time.perf_counter() - start


def run_sync_primitives(iters: int, rounds: int) -> dict[str, Any]:
    """Semaphore + Barrier primitive throughput (beyond Mutex/RWLock)."""
    sem_wall = _measure(lambda: _semaphore_wall(iters), rounds)
    barr_wall = _measure(lambda: _barrier_wall(iters), rounds)
    return {
        "semaphore_ops_per_sec": round(_ops_per_sec(iters, sem_wall), 0),
        "us_per_semaphore_op": round(sem_wall / iters * 1_000_000, 3),
        "barrier_ops_per_sec": round(_ops_per_sec(iters, barr_wall), 0),
        "us_per_barrier_op": round(barr_wall / iters * 1_000_000, 3),
    }


# ── VFS read/write ─────────────────────────────────────────────────────────


def _vfs_wall(iters: int) -> float:
    """VFS virtual-file read+write round trips (in-memory, no disk)."""
    from l1.kernel.vfs import MountType, get_vfs

    vfs = get_vfs()
    vfs.mount("/bench", MountType.VIRTUAL, min_ring=0)
    vfs.write("/bench/rw", "x" * 256, agent_ring=0)
    start = time.perf_counter()
    for _ in range(iters):
        vfs.read("/bench/rw", agent_ring=0)
        vfs.write("/bench/rw", "y" * 256, agent_ring=0)
    return time.perf_counter() - start


def run_vfs(iters: int, rounds: int) -> dict[str, Any]:
    """VFS virtual-file read+write throughput."""
    wall = _measure(lambda: _vfs_wall(iters), rounds)
    return {
        "read_write_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_read_write": round(wall / iters * 1_000_000, 3),
    }


# ── IPC LockChannel throughput ─────────────────────────────────────────────


def _ipc_wall(iters: int) -> float:
    """LockBus LockChannel send round trips (single thread)."""
    from l1.kernel.ipc import LockMessage, LockOp, get_lock_bus

    ch = get_lock_bus().get_channel("bench:ipc")
    start = time.perf_counter()
    for _ in range(iters):
        ch.send(LockMessage(op=LockOp.STATUS, lock_name="bench:ipc", agent_id="agent_a"))
    return time.perf_counter() - start


def run_ipc(iters: int, rounds: int) -> dict[str, Any]:
    """IPC LockChannel send throughput."""
    wall = _measure(lambda: _ipc_wall(iters), rounds)
    return {
        "send_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_send": round(wall / iters * 1_000_000, 3),
    }


# ── Skill retrieval ────────────────────────────────────────────────────────


def _skill_wall(iters: int) -> float:
    """SkillManager.query() TF-IDF retrieval cost."""
    from l1.kernel.skill import get_skill_manager

    sm = get_skill_manager()
    start = time.perf_counter()
    for _ in range(iters):
        sm.query("coding review deployment")
    return time.perf_counter() - start


def run_skill(iters: int, rounds: int) -> dict[str, Any]:
    """Skill query() retrieval throughput."""
    wall = _measure(lambda: _skill_wall(iters), rounds)
    return {
        "queries_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_query": round(wall / iters * 1_000_000, 3),
    }


# ── Process table (PCB) ────────────────────────────────────────────────────


def _process_wall(iters: int) -> float:
    """ProcessTable spawn+get_by_name+exit round trips."""
    from l1.kernel.process import get_table

    tbl = get_table()
    start = time.perf_counter()
    for i in range(iters):
        name = f"proc_{i}"
        pcb = tbl.spawn(name, role="bench")
        tbl.get_by_name(name)
        tbl.exit(pcb.pid)
    return time.perf_counter() - start


def run_process(iters: int, rounds: int) -> dict[str, Any]:
    """ProcessTable spawn→lookup→exit throughput."""
    wall = _measure(lambda: _process_wall(iters), rounds)
    return {
        "lifecycle_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_spawn_exit": round(wall / iters * 1_000_000, 3),
    }


# ── Interrupt dispatch ─────────────────────────────────────────────────────


def _interrupt_wall(iters: int) -> float:
    """InterruptTable.fire() dispatch + history cost."""
    from l1.kernel.interrupt import InterruptType, get_table

    tbl = get_table()
    start = time.perf_counter()
    for _ in range(iters):
        tbl.fire(InterruptType.RESOURCE_EXHAUSTION, agent_id="agent_a", reason="bench")
    return time.perf_counter() - start


def run_interrupt(iters: int, rounds: int) -> dict[str, Any]:
    """InterruptTable.fire() dispatch throughput."""
    wall = _measure(lambda: _interrupt_wall(iters), rounds)
    return {
        "fire_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_fire": round(wall / iters * 1_000_000, 3),
    }


# ── Territory path matching ────────────────────────────────────────────────


def _territory_wall(iters: int) -> float:
    """territory.is_within() path-in-subtree match cost."""
    from l1.kernel.territory import is_within

    bases = ["/project", "/sandbox", "/tmp"]
    start = time.perf_counter()
    for _ in range(iters):
        is_within("/project/foo/bar.py", bases)
    return time.perf_counter() - start


def run_territory(iters: int, rounds: int) -> dict[str, Any]:
    """territory.is_within() path-match throughput."""
    wall = _measure(lambda: _territory_wall(iters), rounds)
    return {
        "match_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_match": round(wall / iters * 1_000_000, 3),
    }


# ── Reputation ─────────────────────────────────────────────────────────────


def _reputation_wall(iters: int) -> float:
    """ReputationSystem get+set round trips."""
    from l1.kernel.reputation import get_reputation

    rep = get_reputation()
    start = time.perf_counter()
    for i in range(iters):
        rep.get(f"agent_{i % 64}")
        rep.set(f"agent_{i % 64}", float(i % 100) / 10.0)
    return time.perf_counter() - start


def run_reputation(iters: int, rounds: int) -> dict[str, Any]:
    """Reputation get+set throughput."""
    wall = _measure(lambda: _reputation_wall(iters), rounds)
    return {
        "get_set_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_get_set": round(wall / iters * 1_000_000, 3),
    }


# ── Persistence (SQLite append) ────────────────────────────────────────────


def _persist_wall(iters: int) -> float:
    """persist.append() SQLite insert cost (batched commit), isolated to a temp DB."""
    import tempfile

    import l1.kernel.persist as persist

    # Isolate from the live events DB: point the module-level path at a
    # throwaway file and restore afterwards, so the default benchmark run
    # never durably pollutes application state.
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        saved_path, saved_db = persist._DB_PATH, persist._DB
        persist._DB_PATH, persist._DB = tmp.name, None
        try:
            start = time.perf_counter()
            for i in range(iters):
                persist.append("bench.event", {"i": i})
            return time.perf_counter() - start
        finally:
            persist._DB_PATH, persist._DB = saved_path, saved_db


def run_persist(iters: int, rounds: int) -> dict[str, Any]:
    """persist.append() SQLite insert throughput."""
    wall = _measure(lambda: _persist_wall(iters), rounds)
    return {
        "append_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_append": round(wall / iters * 1_000_000, 3),
    }


# ── Resource limiter ───────────────────────────────────────────────────────


def _resource_wall(iters: int) -> float:
    """ResourceLimiter check+release round trips."""
    from l1.kernel.resource import get_limiter

    lim = get_limiter()
    start = time.perf_counter()
    for i in range(iters):
        lim.check(f"agent_{i % 64}", "tokens", cost=1)
        lim.release(f"agent_{i % 64}", "tokens", cost=1)
    return time.perf_counter() - start


def run_resource(iters: int, rounds: int) -> dict[str, Any]:
    """ResourceLimiter check+release throughput."""
    wall = _measure(lambda: _resource_wall(iters), rounds)
    return {
        "check_release_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_check_release": round(wall / iters * 1_000_000, 3),
    }


# ── IPC request→respond round trip ────────────────────────────────────────


def _ipc_rtt_wall(iters: int) -> float:
    """LockChannel request→respond full round trip (requester + responder).

    A responder thread calls respond() for every pending request, so each
    request() blocks until its reply arrives — measuring the true send→reply
    synchronisation cost, not just the fire-and-forget send() path.
    """
    from l1.kernel.ipc import LockMessage, LockOp, get_lock_bus

    ch = get_lock_bus().get_channel("bench:rtt")
    stop = threading.Event()
    in_flight = threading.Semaphore(0)
    pending_id: list[str] = []

    def _responder() -> None:
        while not stop.is_set():
            if not in_flight.acquire(timeout=0.01):
                continue
            msg_id = pending_id.pop(0)
            ch.respond(msg_id, {"ok": True})

    resp = threading.Thread(target=_responder, daemon=True)
    resp.start()
    start = time.perf_counter()
    try:
        for i in range(iters):
            msg = LockMessage(op=LockOp.STATUS, lock_name="bench:rtt", agent_id=f"agent_{i}")
            pending_id.append(msg.msg_id)
            in_flight.release()
            ch.request(msg)
    finally:
        stop.set()
        resp.join(timeout=2)
    return time.perf_counter() - start


def run_ipc_rtt(iters: int, rounds: int) -> dict[str, Any]:
    """IPC LockChannel request→respond round-trip throughput."""
    wall = _measure(lambda: _ipc_rtt_wall(iters), rounds)
    return {
        "rtt_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_rtt": round(wall / iters * 1_000_000, 3),
    }


# ── Diff codec / data chain (L4) ─────────────────────────────────────────


def _diff_header_wall(iters: int) -> float:
    """diff_frame build_frame_header + parse_frame_header round trip."""
    from l4.sandbox.diff_frame import build_frame_header, parse_frame_header

    start = time.perf_counter()
    for _ in range(iters):
        h = build_frame_header(frame_type=2, threshold_score=64, bitmask=3, hunk_count=12)
        _ = parse_frame_header(h)
    return time.perf_counter() - start


def run_diff_header(iters: int, rounds: int) -> dict[str, Any]:
    """Diff frame header build+parse throughput (nanosecond fast path)."""
    wall = _measure(lambda: _diff_header_wall(iters), rounds)
    return {
        "header_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_header": round(wall / iters * 1_000_000, 3),
    }


def _diff_hunk_wall(iters: int) -> float:
    """diff_codec encode_hunks + decode_hunks round trip (multi-hunk payload)."""
    from l4.sandbox.diff_codec import decode_hunks, encode_hunks

    # Real diff_codec schema: string type codes, start offsets, and lines
    # split into added/removed. Assert the round trip so a future schema
    # drift fails loudly instead of silently measuring empty hunks.
    hunks = [
        {
            "type": "insert",
            "original_start": 1,
            "modified_start": 1,
            "added_lines": ["def foo():\n", "\n"],
            "removed_lines": [],
        },
        {
            "type": "replace",
            "original_start": 10,
            "modified_start": 12,
            "added_lines": ["new line\n"],
            "removed_lines": ["old line\n"],
        },
        {
            "type": "insert",
            "original_start": 20,
            "modified_start": 25,
            "added_lines": ["import os\n", "import sys\n"],
            "removed_lines": [],
        },
    ]
    assert decode_hunks(encode_hunks(hunks)) == hunks, "diff_codec round trip drifted"
    start = time.perf_counter()
    for _ in range(iters):
        encoded = encode_hunks(hunks)
        _ = decode_hunks(encoded)
    return time.perf_counter() - start


def run_diff_hunk(iters: int, rounds: int) -> dict[str, Any]:
    """Diff hunk encode+decode throughput (3-hunk, zlib+JSON)."""
    wall = _measure(lambda: _diff_hunk_wall(iters), rounds)
    return {
        "hunk_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_hunk_roundtrip": round(wall / iters * 1_000_000, 3),
    }


def _diff_compress_wall(iters: int) -> float:
    """diff_codec compress_record + decompress_record round trip (large payload)."""
    from l4.sandbox.diff_codec import compress_record, decompress_record

    long_text = "\n".join(f"@@ -{i},{i + 3} +{i},{i + 4} @@\n+def func_{i}():\n    pass" for i in range(50))
    record = {"diff_id": "d1", "ts": 1234.5, "meta": {"path": "/a.py"}, "stitched": long_text}
    start = time.perf_counter()
    for _ in range(iters):
        compressed = compress_record(record)
        _ = decompress_record(compressed)
    return time.perf_counter() - start


def run_diff_compress(iters: int, rounds: int) -> dict[str, Any]:
    """Diff record compress+decompress throughput (zlib, ~3KB stitched)."""
    wall = _measure(lambda: _diff_compress_wall(iters), rounds)
    return {
        "compress_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_compress_roundtrip": round(wall / iters * 1_000_000, 3),
    }


def _json_parse_wall(iters: int, payload_size: int) -> float:
    """Large JSON payload parse cost (LLM response simulation)."""
    import json as _json

    # Build a realistic LLM-style response payload (~payload_size bytes)
    choices = [{"index": i, "message": {"role": "assistant", "content": "x" * 500}} for i in range(50)]
    payload = _json.dumps(
        {"id": "chatcmpl-xxx", "choices": choices, "usage": {"prompt_tokens": 100, "completion_tokens": 500}}
    )
    # Pad to payload_size
    size = len(payload)
    if size < payload_size:
        payload += " " * (payload_size - size)
    start = time.perf_counter()
    for _ in range(iters):
        _ = _json.loads(payload)
    return time.perf_counter() - start


def run_json_parse(iters: int, payload_size: int, rounds: int) -> dict[str, Any]:
    """Large JSON payload parse throughput (LLM response chain)."""
    wall = _measure(lambda: _json_parse_wall(iters, payload_size), rounds)
    return {
        "parse_ops_per_sec": round(_ops_per_sec(iters, wall), 0),
        "us_per_parse": round(wall / iters * 1_000_000, 3),
        "payload_bytes": payload_size,
    }


# ── Orchestration ──────────────────────────────────────────────────────────


def run_all(agent_counts: list[int], rounds: int) -> dict[str, Any]:
    """Run every metric family and return a combined report dict."""
    return {
        "amdahl_l1": run_amdahl_l1(agent_counts, EVAL_AMDAHL_TOTAL_WORK_ITEMS, rounds),
        "lock_contention": run_lock_contention(EVAL_LOCK_CONTEND_WORKERS, EVAL_LOCK_CONTEND_TOTAL_OPS, rounds),
        "lock_vs_lockfree": run_lock_vs_lockfree(EVAL_LOCKFREE_ITERS, rounds),
        "scheduling_latency": run_scheduling_latency(EVAL_SCHED_LATENCY_TASKS),
        "queue_event": run_queue_event(
            EVAL_QUEUE_ITERS,
            EVAL_EVENT_ITERS,
            EVAL_EVENT_LISTENERS,
            rounds,
            bounded_event_iters=EVAL_EVENT_BOUNDED_ITERS,
        ),
        "constitution": run_constitution(EVAL_CONSTITUTION_ITERS, rounds),
        "memory": run_memory(EVAL_MEMORY_ALLOC_ITERS, rounds),
        "gatechain": run_gatechain(EVAL_GATECHAIN_ITERS, rounds),
        "memory_reclaim": run_memory_reclaim(EVAL_RECLAIM_ITERS, EVAL_SWAP_ITERS, EVAL_PRESSURE_AGENTS, rounds),
        "alloc_shards": run_alloc_shards(EVAL_ALLOC_SHARD_WORKERS, EVAL_MEMORY_ALLOC_ITERS, rounds),
        "sync_primitives": run_sync_primitives(EVAL_SYNC_ITERS, rounds),
        "vfs": run_vfs(EVAL_VFS_ITERS, rounds),
        "ipc": run_ipc(EVAL_IPC_ITERS, rounds),
        "skill": run_skill(EVAL_SKILL_ITERS, rounds),
        "process": run_process(EVAL_PROCESS_ITERS, rounds),
        "interrupt": run_interrupt(EVAL_INTERRUPT_ITERS, rounds),
        "territory": run_territory(EVAL_TERRITORY_ITERS, rounds),
        "reputation": run_reputation(EVAL_REPUTATION_ITERS, rounds),
        "persist": run_persist(EVAL_PERSIST_ITERS, rounds),
        "resource": run_resource(EVAL_RESOURCE_ITERS, rounds),
        "ipc_rtt": run_ipc_rtt(EVAL_IPC_RTT_ITERS, rounds),
        "diff_header": run_diff_header(EVAL_DIFF_HEADER_ITERS, rounds),
        "diff_hunk": run_diff_hunk(EVAL_DIFF_HUNK_ITERS, rounds),
        "diff_compress": run_diff_compress(EVAL_DIFF_COMPRESS_ITERS, rounds),
        "json_parse": run_json_parse(EVAL_JSON_PARSE_ITERS, EVAL_JSON_PAYLOAD_BYTES, rounds),
    }


def print_report(platform_info: dict[str, Any], report: dict[str, Any]) -> None:
    """Print a human-readable full benchmark report."""
    print("=" * 68)
    print("Praxis kernel scaling + hard-metric benchmark")
    print("=" * 68)
    print(f"  system : {platform_info['system']} {platform_info['release']} ({platform_info['machine']})")
    if platform_info.get("wsl"):
        print("  wsl    : yes (Linux kernel running under WSL)")
    print(f"  python : {platform_info['python']}  cpus: {platform_info['cpu_count']}")
    print("-" * 68)

    c = report.get("amdahl_l1")
    if c is not None:
        print(f"\n  Amdahl L1 scheduler + Mutex + RingChannel — serial P={c['serial_fraction_p']:.3f}")
        print(f"    work set: {c['fixed_total_work_items']:,} items per worker-count sample; {c['verdict']}")
        print(
            f"    {'workers':<8} {'wall(s)':>10} {'ops/s':>12} {'p95 op(ms)':>12} {'p95 lock(ms)':>14} {'p95 queue(ms)':>15}"
        )
        for i, n in enumerate(c["agent_counts"]):
            print(
                f"    {n:<8} {c['wall_times'][i]:>10.3f} {c['throughput_ops_per_sec'][i]:>12,.0f} "
                f"{c['operation_latency_p95_ms'][i]:>12.3f} {c['lock_wait_p95_ms'][i]:>14.3f} "
                f"{c['queue_wait_p95_ms'][i]:>15.3f}"
            )

    lc = report.get("lock_contention")
    if lc:
        print("\n  Lock contention (fixed total work, throughput, speedup, and wait):")
        for kind in ("mutex", "rwlock"):
            print(f"    {kind}:")
            for n, m in lc[kind].items():
                print(
                    f"      {n}w: {m['ops_per_sec']:>10,.0f} ops/s  speedup={m['speedup_vs_single']:.2f} "
                    f"eff={m['parallel_efficiency']:.2f} p95-wait={m['lock_wait_p95_ms']:.3f}ms"
                )

    lv = report.get("lock_vs_lockfree")
    if lv:
        print(
            f"\n  Locked vs lock-free: locked={lv['locked_ops_per_sec']:,.0f} "
            f"lockfree={lv['lockfree_ops_per_sec']:,.0f} overhead={lv['lock_overhead_ratio']:.2f}x"
        )

    sl = report.get("scheduling_latency")
    if sl:
        print(f"  Scheduling latency: p50={sl['p50_ms']:.3f}ms p95={sl['p95_ms']:.3f}ms max={sl['max_ms']:.3f}ms")

    qe = report.get("queue_event")
    if qe:
        print(f"  RingChannel put+get: {qe['queue_put_get_ops_per_sec']:,.0f} ops/s")
        curves = [("normal", qe["event_bus"])]
        if qe.get("bounded_event_bus") is not None:
            curves.append(("bounded", qe["bounded_event_bus"]))
        for label, curve in curves:
            for n, m in curve.items():
                if m["clean"]:
                    status = "clean"
                elif not m["drained"]:
                    status = f"not-drained depth={m['queue_depth']}"
                else:
                    status = f"dropped={m['dropped']} ({m['drop_rate']:.2%})"
                print(f"  Event-bus {label} emit ({n} listeners): {m['ops_per_sec']:,.0f} ops/s [{status}]")

    con = report.get("constitution")
    if con:
        print(
            f"  Constitution.check(): {con['checks_per_sec']:,.0f} checks/s "
            f"({con['us_per_check']:.3f} us/check, {con['rules_evaluated_per_check']} rules)"
        )

    mem = report.get("memory")
    if mem:
        print(
            f"  Allocator alloc+free: {mem['alloc_free_ops_per_sec']:,.0f} ops/s ({mem['us_per_alloc_free']:.3f} us/op)"
        )
        print(
            f"  Allocator reclaim:    {mem['reclaim_ops_per_sec']:,.0f} ops/s ({mem['us_per_reclaim_call']:.3f} us/call)"
        )

    if "gatechain" in report:
        gc = report["gatechain"]
        print(f"  GateChain check():   {gc['checks_per_sec']:,.0f} checks/s ({gc['us_per_check']:.3f} us/check)")

    if "memory_reclaim" in report:
        mr = report["memory_reclaim"]
        print(
            f"  Allocator pressure(): {mr['pressure_scan_ops_per_sec']:,.0f} scans/s ({mr['pressure_agents']} agents)"
        )
        print(f"  Allocator swap_out(): {mr['swap_out_ops_per_sec']:,.0f} ops/s ({mr['us_per_swap_out']:.3f} us/op)")

    if "alloc_shards" in report:
        print("  Allocator shard contention (ops/s vs workers, eff vs single):")
        for n, m in report["alloc_shards"].items():
            print(f"      {n}w: {m['ops_per_sec']:>10,.0f} ops/s  eff={m['efficiency_vs_single']:.2f}")

    if "sync_primitives" in report:
        sp = report["sync_primitives"]
        print(
            f"  Semaphore: {sp['semaphore_ops_per_sec']:,.0f} ops/s ({sp['us_per_semaphore_op']:.3f} us)  "
            f"Barrier: {sp['barrier_ops_per_sec']:,.0f} ops/s ({sp['us_per_barrier_op']:.3f} us)"
        )

    if "vfs" in report:
        v = report["vfs"]
        print(f"  VFS read+write:      {v['read_write_ops_per_sec']:,.0f} ops/s ({v['us_per_read_write']:.3f} us/op)")

    if "ipc" in report:
        ipc = report["ipc"]
        print(f"  IPC LockChannel send:{ipc['send_ops_per_sec']:,.0f} ops/s ({ipc['us_per_send']:.3f} us/send)")

    if "skill" in report:
        sk = report["skill"]
        print(f"  Skill query():       {sk['queries_per_sec']:,.0f} queries/s ({sk['us_per_query']:.3f} us/query)")

    if "process" in report:
        p = report["process"]
        print(
            f"  Process spawn→exit:  {p['lifecycle_ops_per_sec']:,.0f} ops/s "
            f"({p['us_per_spawn_exit']:.3f} us/lifecycle)"
        )

    if "interrupt" in report:
        ir = report["interrupt"]
        print(f"  Interrupt fire():    {ir['fire_ops_per_sec']:,.0f} fires/s ({ir['us_per_fire']:.3f} us/fire)")

    if "territory" in report:
        t = report["territory"]
        print(f"  territory.is_within():{t['match_ops_per_sec']:,.0f} matches/s ({t['us_per_match']:.3f} us/match)")

    if "reputation" in report:
        r = report["reputation"]
        print(f"  Reputation get+set:  {r['get_set_ops_per_sec']:,.0f} ops/s ({r['us_per_get_set']:.3f} us/op)")

    if "persist" in report:
        ps = report["persist"]
        print(f"  persist.append():    {ps['append_ops_per_sec']:,.0f} appends/s ({ps['us_per_append']:.3f} us/append)")

    if "resource" in report:
        rc = report["resource"]
        print(
            f"  ResourceLimiter:     {rc['check_release_ops_per_sec']:,.0f} checks/s "
            f"({rc['us_per_check_release']:.3f} us/check+release)"
        )

    if "ipc_rtt" in report:
        irt = report["ipc_rtt"]
        print(f"  IPC request→respond: {irt['rtt_ops_per_sec']:,.0f} RTT/s ({irt['us_per_rtt']:.3f} us/RTT)")

    if "diff_header" in report:
        dh = report["diff_header"]
        print(f"  Diff frame header:   {dh['header_ops_per_sec']:,.0f} ops/s ({dh['us_per_header']:.3f} us/op)")

    if "diff_hunk" in report:
        dh = report["diff_hunk"]
        print(
            f"  Diff hunk enc+dec:   {dh['hunk_ops_per_sec']:,.0f} ops/s "
            f"({dh['us_per_hunk_roundtrip']:.3f} us/roundtrip)"
        )

    if "diff_compress" in report:
        dc = report["diff_compress"]
        print(
            f"  Diff compress+decomp:{dc['compress_ops_per_sec']:,.0f} ops/s "
            f"({dc['us_per_compress_roundtrip']:.3f} us/roundtrip)"
        )

    if "json_parse" in report:
        jp = report["json_parse"]
        print(
            f"  JSON parse ({jp['payload_bytes']}B): {jp['parse_ops_per_sec']:,.0f} ops/s "
            f"({jp['us_per_parse']:.3f} us/parse)"
        )
    print("=" * 68)


def _parse_agent_counts(value: str) -> list[int]:
    """Parse a positive, ascending Amdahl worker-count sweep beginning at one."""
    try:
        agent_counts = [int(item) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise ValueError("--agents must be a comma-separated list of integers") from exc
    if not agent_counts or any(count < 1 for count in agent_counts):
        raise ValueError("--agents must contain at least one positive worker count")
    if agent_counts[0] != 1 or agent_counts != sorted(set(agent_counts)):
        raise ValueError("--agents must be an ascending unique sweep starting with 1")
    return agent_counts


def main() -> int:
    """Entry point: run selected metrics, print and optionally dump JSON."""
    parser = argparse.ArgumentParser(description="Praxis kernel scaling + hard-metric benchmark")
    parser.add_argument(
        "--agents", type=str, default=",".join(str(a) for a in EVAL_AMDAHL_AGENTS), help="comma-separated worker counts"
    )
    parser.add_argument("--rounds", type=int, default=EVAL_AMDAHL_ROUNDS, help="median rounds per metric")
    parser.add_argument(
        "--mode",
        type=str,
        default="all",
        choices=[
            "all",
            "amdahl",
            "lock",
            "latency",
            "queue",
            "constitution",
            "memory",
            "gatechain",
            "reclaim",
            "shards",
            "sync",
            "vfs",
            "ipc",
            "skill",
            "process",
            "interrupt",
            "territory",
            "reputation",
            "persist",
            "resource",
            "ipc_rtt",
            "diff",
            "json",
        ],
        help="which metric family to run",
    )
    parser.add_argument("--json", type=str, default="", help="write machine-readable report to this file")
    args = parser.parse_args()

    try:
        agent_counts = _parse_agent_counts(args.agents)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.rounds < 1:
        print("error: --rounds must be positive", file=sys.stderr)
        return 2

    platform_info = collect_platform_info()

    if args.mode == "amdahl":
        report = {
            "amdahl_l1": run_amdahl_l1(agent_counts, EVAL_AMDAHL_TOTAL_WORK_ITEMS, args.rounds),
        }
    elif args.mode == "lock":
        report = {
            "lock_contention": run_lock_contention(EVAL_LOCK_CONTEND_WORKERS, EVAL_LOCK_CONTEND_TOTAL_OPS, args.rounds),
            "lock_vs_lockfree": run_lock_vs_lockfree(EVAL_LOCKFREE_ITERS, args.rounds),
        }
    elif args.mode == "latency":
        report = {"scheduling_latency": run_scheduling_latency(EVAL_SCHED_LATENCY_TASKS)}
    elif args.mode == "queue":
        report = {
            "queue_event": run_queue_event(
                EVAL_QUEUE_ITERS,
                EVAL_EVENT_ITERS,
                EVAL_EVENT_LISTENERS,
                args.rounds,
                bounded_event_iters=EVAL_EVENT_BOUNDED_ITERS,
            )
        }
    elif args.mode == "constitution":
        report = {"constitution": run_constitution(EVAL_CONSTITUTION_ITERS, args.rounds)}
    elif args.mode == "memory":
        report = {"memory": run_memory(EVAL_MEMORY_ALLOC_ITERS, args.rounds)}
    elif args.mode == "gatechain":
        report = {"gatechain": run_gatechain(EVAL_GATECHAIN_ITERS, args.rounds)}
    elif args.mode == "reclaim":
        report = {
            "memory_reclaim": run_memory_reclaim(EVAL_RECLAIM_ITERS, EVAL_SWAP_ITERS, EVAL_PRESSURE_AGENTS, args.rounds)
        }
    elif args.mode == "shards":
        report = {"alloc_shards": run_alloc_shards(EVAL_ALLOC_SHARD_WORKERS, EVAL_MEMORY_ALLOC_ITERS, args.rounds)}
    elif args.mode == "sync":
        report = {"sync_primitives": run_sync_primitives(EVAL_SYNC_ITERS, args.rounds)}
    elif args.mode == "vfs":
        report = {"vfs": run_vfs(EVAL_VFS_ITERS, args.rounds)}
    elif args.mode == "ipc":
        report = {"ipc": run_ipc(EVAL_IPC_ITERS, args.rounds)}
    elif args.mode == "skill":
        report = {"skill": run_skill(EVAL_SKILL_ITERS, args.rounds)}
    elif args.mode == "process":
        report = {"process": run_process(EVAL_PROCESS_ITERS, args.rounds)}
    elif args.mode == "interrupt":
        report = {"interrupt": run_interrupt(EVAL_INTERRUPT_ITERS, args.rounds)}
    elif args.mode == "territory":
        report = {"territory": run_territory(EVAL_TERRITORY_ITERS, args.rounds)}
    elif args.mode == "reputation":
        report = {"reputation": run_reputation(EVAL_REPUTATION_ITERS, args.rounds)}
    elif args.mode == "persist":
        report = {"persist": run_persist(EVAL_PERSIST_ITERS, args.rounds)}
    elif args.mode == "resource":
        report = {"resource": run_resource(EVAL_RESOURCE_ITERS, args.rounds)}
    elif args.mode == "ipc_rtt":
        report = {"ipc_rtt": run_ipc_rtt(EVAL_IPC_RTT_ITERS, args.rounds)}
    elif args.mode == "diff":
        report = {
            "diff_header": run_diff_header(EVAL_DIFF_HEADER_ITERS, args.rounds),
            "diff_hunk": run_diff_hunk(EVAL_DIFF_HUNK_ITERS, args.rounds),
            "diff_compress": run_diff_compress(EVAL_DIFF_COMPRESS_ITERS, args.rounds),
        }
    elif args.mode == "json":
        report = {"json_parse": run_json_parse(EVAL_JSON_PARSE_ITERS, EVAL_JSON_PAYLOAD_BYTES, args.rounds)}
    else:  # all
        report = run_all(agent_counts, args.rounds)

    print_report(platform_info, report)

    if args.json:
        out = {"platform": platform_info, **report}
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, sort_keys=True)
        print(f"JSON report written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
