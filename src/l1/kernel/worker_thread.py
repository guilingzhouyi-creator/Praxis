"""WorkerPort adapter — fixed-size thread pool with bounded queue.

Backed by a ``threading.Thread`` pool + ``queue.Queue`` for backpressure.
Supports graceful shutdown, idle timeout, and usage stats.

Usage:
    from l1.kernel.worker_thread import ThreadPoolWorker
    pool = ThreadPoolWorker(min_workers=4, max_workers=32)
    result = pool.submit(some_fn, arg1, arg2)
    pool.shutdown(wait=True)
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from l1.kernel.load_adaptive import (
    Action,
    ControllerMetrics,
    Decision,
    LoadAdaptiveController,
)
from l1.kernel.params.api import (
    LOAD_ADAPTIVE_ENABLED,
    LOAD_ADAPTIVE_SAMPLE_INTERVAL,
    WORKER_POOL_IDLE_TIMEOUT,
    WORKER_POOL_MAX,
    WORKER_POOL_MIN,
    WORKER_POOL_QUEUE_SIZE,
    WORKER_POOL_TASK_TIMEOUT,
)
from l1.kernel.ports import Result, TaskHandle, WorkerPort

logger = logging.getLogger(__name__)


class _Worker(threading.Thread):
    """Internal worker thread — pulls callables from the job queue."""

    def __init__(self, pool: ThreadPoolWorker, idx: int) -> None:
        super().__init__(daemon=True, name=f"worker-{idx}")
        self._pool = pool
        self._idx = idx

    def run(self) -> None:
        """Main worker loop — execute queued tasks until retired or shut down."""
        pool = self._pool
        while True:
            try:
                item = pool._queue.get(timeout=pool._idle_timeout)
            except queue.Empty:
                # Idle timeout — re-check queue non-blocking before retiring
                try:
                    item = pool._queue.get_nowait()
                except queue.Empty:
                    # Queue still empty — try to shrink
                    if not pool._try_shrink(self):
                        continue  # pool said no, keep polling
                    return  # we were retired
                # Got an item from the non-blocking check — process it below
            if item is None:  # sentinel: shutdown
                pool._queue.task_done()
                return
            fn, args, kwargs, result_holder, handle = item
            t0 = time.monotonic()
            try:
                with pool._lock:
                    pool._active += 1
                value = fn(*args, **kwargs)
                result_holder["success"] = True
                if handle is not None:
                    handle.set_result(value)
            except Exception as e:
                result_holder["success"] = False
                result_holder["error"] = str(e)
                if handle is not None:
                    handle.set_exception(e)
                logger.debug("worker-%d: task failed: %s", self._idx, e)
            finally:
                elapsed = time.monotonic() - t0
                # Single critical section per task (was three acquisitions):
                # decrement active, bump completed, and record elapsed together
                # to cut the per-task lock churn that drove CPU anti-scaling.
                with pool._lock:
                    pool._active -= 1
                    pool._completed += 1
                    pool._record_task_elapsed_locked(elapsed)
                pool._queue.task_done()


class ThreadPoolWorker(WorkerPort):
    """Fixed-size thread pool implementing WorkerPort.

    Dynamic sizing between *min_workers* and *max_workers*:
      - Starts with *min_workers* threads.
      - Grows up to *max_workers* when the queue backs up.
      - Shrinks back toward *min_workers* after *idle_timeout* of inactivity.
    """

    def __init__(
        self,
        min_workers: int = WORKER_POOL_MIN,
        max_workers: int = WORKER_POOL_MAX,
        queue_size: int = WORKER_POOL_QUEUE_SIZE,
        idle_timeout: float = WORKER_POOL_IDLE_TIMEOUT,
        task_timeout: float = WORKER_POOL_TASK_TIMEOUT,
    ) -> None:
        if max_workers < min_workers:
            max_workers = min_workers
        self._min = min_workers
        self._max = max_workers
        self._queue_size = queue_size
        self._idle_timeout = idle_timeout
        self._task_timeout = task_timeout
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._workers: list[_Worker] = []
        # RLock: _grow() calls _add_worker() while holding this lock, and
        # _add_worker() re-acquires it (AGENTS.md reentrant-lock convention).
        self._lock = threading.RLock()
        self._active = 0
        self._completed = 0
        self._rejected = 0
        self._shutdown = False
        self._next_idx = 0
        self._controller = LoadAdaptiveController() if LOAD_ADAPTIVE_ENABLED else None
        self._sample_interval = LOAD_ADAPTIVE_SAMPLE_INTERVAL
        self._sampler_thread: threading.Thread | None = None
        self._task_elapsed_sum = 0.0
        self._task_elapsed_count = 0

        # Start minimum workers
        for _ in range(min_workers):
            self._add_worker()

        # Start the background sampler if adaptive control is enabled
        if self._controller is not None:
            self._start_sampler()

    # ── WorkerPort interface ───────────────────────────────────────────────

    def submit(self, fn: Callable, *args: Any, **kwargs: Any) -> Result:
        """Submit a callable for execution (fire-and-forget). Returns immediately.

        If the queue is full, the oldest pending task is dropped (FIFO eviction).
        """
        return self._enqueue(fn, args, kwargs, handle=None)

    def submit_result(self, fn: Callable, *args: Any, **kwargs: Any) -> TaskHandle:
        """Submit a callable and return a TaskHandle carrying its result/exception.

        The completion contract missing from ``submit()``: the returned handle's
        ``.result(timeout)`` blocks for the value (or re-raises the task error).
        If the task is dropped by backpressure the handle never completes, so
        always pass a timeout when awaiting.
        """
        handle = TaskHandle()
        self._enqueue(fn, args, kwargs, handle=handle)
        return handle

    def _enqueue(self, fn: Callable, args: tuple, kwargs: dict, handle: TaskHandle | None) -> Result:
        """Shared enqueue path for submit / submit_result (backpressure + grow)."""
        if self._shutdown:
            self._rejected += 1
            return Result.fail("pool is shut down")

        result_holder: dict = {"success": False, "error": ""}
        item = (fn, args, kwargs, result_holder, handle)

        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # Backpressure: drop oldest pending task
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(item)
                self._rejected += 1  # the dropped one
            except queue.Empty:
                self._rejected += 1
                return Result.fail("queue full and eviction failed")

        # Adaptive controller handles sizing via the sampler thread.
        # Fallback: simple heuristic when adaptive control is disabled.
        if self._controller is None and self._queue.qsize() > len(self._workers) * 2:
            self._grow()

        return Result.ok(submitted=True)

    def shutdown(self, wait: bool = True, timeout: float | None = None) -> Result:
        """Shut down the pool. Sends sentinel per worker to drain the queue."""
        self._shutdown = True
        with self._lock:
            n = len(self._workers)
        for _ in range(n):
            self._queue.put(None)  # sentinel
        if wait:
            deadline = None if timeout is None else time.monotonic() + timeout
            for w in list(self._workers):
                remaining = deadline - time.monotonic() if deadline else None
                if remaining is not None and remaining <= 0:
                    break
                w.join(timeout=remaining)
        with self._lock:
            self._workers.clear()
        return Result.ok(shutdown=True)

    def stats(self) -> dict:
        """Return pool sizing, activity, and throughput counters."""
        with self._lock:
            result = {
                "pool_size": len(self._workers),
                "active": self._active,
                "queued": self._queue.qsize(),
                "completed": self._completed,
                "rejected": self._rejected,
                "min": self._min,
                "max": self._max,
                "shutdown": self._shutdown,
            }
            if self._controller is not None:
                result["controller"] = self._controller.state()
            return result

    # ── Internal ──────────────────────────────────────────────────────────

    def _add_worker(self) -> _Worker:
        with self._lock:
            w = _Worker(self, self._next_idx)
            self._next_idx += 1
            self._workers.append(w)
            w.start()
            return w

    def _grow(self) -> None:
        with self._lock:
            current = len(self._workers)
            if current >= self._max:
                return
            target = min(current + 2, self._max)
            for _ in range(target - current):
                self._add_worker()
            logger.debug("pool grew: %d → %d workers", current, target)

    def _try_shrink(self, worker: _Worker) -> bool:
        """Attempt to retire *worker*. Returns True if the worker should exit."""
        with self._lock:
            current = len(self._workers)
            if current <= self._min or self._shutdown:
                return False
            try:
                self._workers.remove(worker)
            except ValueError:
                # Already retired on an earlier idle tick — confirm the exit
                # instead of returning False, which would make the thread
                # spin on the queue forever (worker-thread leak).
                logger.debug("worker-%d: already retired, exiting", worker._idx)
                return True
            logger.debug("pool shrunk: %d → %d workers", current, current - 1)
            return True

    # ── Load-adaptive sampler ────────────────────────────────────────────

    def _start_sampler(self) -> None:
        """Start the background sampling thread (daemon)."""
        if self._sampler_thread is not None and self._sampler_thread.is_alive():
            return
        self._sampler_thread = threading.Thread(target=self._sampler_loop, daemon=True, name="load-adaptive-sampler")
        self._sampler_thread.start()

    def _sampler_loop(self) -> None:
        """Periodic sampling loop: gather metrics and feed the controller."""
        while not self._shutdown:
            time.sleep(self._sample_interval)
            try:
                self._sample_and_decide()
            except Exception:
                logger.exception("load-adaptive sampler error")

    def _sample_and_decide(self) -> None:
        """Sample current pool metrics and apply the controller's decision."""
        if self._controller is None:
            return
        with self._lock:
            wc = len(self._workers)
            qs = self._queue.qsize()
            cap = self._queue.maxsize
            active = self._active
        queue_ratio = (qs / cap) if cap > 0 else 0.0
        active_ratio = (active / wc) if wc > 0 else 0.0
        task_elapsed = (self._task_elapsed_sum / self._task_elapsed_count) if self._task_elapsed_count > 0 else 0.0

        metrics = ControllerMetrics(
            queue_ratio=queue_ratio,
            active_ratio=active_ratio,
            task_elapsed=task_elapsed,
            worker_count=wc,
            worker_min=self._min,
            worker_max=self._max,
        )
        decision = self._controller.decide(metrics)
        self._apply_decision(decision)

    def _apply_decision(self, decision: Decision) -> None:
        """Apply a controller decision to the pool."""
        if decision.action == Action.GROW or decision.action == Action.GROW_FAST:
            with self._lock:
                current = len(self._workers)
                if current >= self._max:
                    return
                target = min(decision.target_workers, self._max)
                for _ in range(target - current):
                    self._add_worker()
                logger.debug(
                    "controller: %s %d → %d (%s)",
                    decision.action.name,
                    current,
                    target,
                    decision.reason,
                )
        elif decision.action == Action.SHRINK:
            # Shrink is handled by idle worker self-retirement in _try_shrink.
            # The controller's target is advisory -- the pool will shrink
            # naturally as workers time out.  No forced retirement here to
            # avoid disturbing in-flight work.
            logger.debug(
                "controller: SHRINK target=%d (%s)",
                decision.target_workers,
                decision.reason,
            )

    def _record_task_elapsed_locked(self, elapsed: float) -> None:
        """Record a task's elapsed time. Caller MUST hold ``self._lock``.

        Lock-free body so the worker's per-task finally block can fold this into
        its single critical section (decrement/complete/record) instead of
        taking the lock a second time.
        """
        self._task_elapsed_sum += elapsed
        self._task_elapsed_count += 1
        # Keep the window bounded: reset after 100 samples to avoid
        # stale averages persisting through load regime changes.
        if self._task_elapsed_count >= 100:
            self._task_elapsed_sum = elapsed
            self._task_elapsed_count = 1
