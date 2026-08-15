"""Tests for the WorkerPort result contract (TaskHandle + submit_result)."""

from __future__ import annotations

import pytest

from l1.kernel.ports import Result, TaskHandle, WorkerPort
from l1.kernel.worker_thread import ThreadPoolWorker


@pytest.fixture
def pool() -> ThreadPoolWorker:
    p = ThreadPoolWorker(min_workers=2, max_workers=4)
    yield p
    p.shutdown(wait=True, timeout=5)


def test_submit_result_returns_value(pool: ThreadPoolWorker) -> None:
    handle = pool.submit_result(lambda a, b: a * b, 6, 7)
    assert isinstance(handle, TaskHandle)
    assert handle.result(timeout=5) == 42
    assert handle.done() is True


def test_submit_result_captures_exception(pool: ThreadPoolWorker) -> None:
    def boom() -> None:
        raise ValueError("kaboom")

    handle = pool.submit_result(boom)
    assert isinstance(handle.exception(timeout=5), ValueError)
    with pytest.raises(ValueError, match="kaboom"):
        handle.result(timeout=5)


def test_submit_still_fire_and_forget(pool: ThreadPoolWorker) -> None:
    done: list[int] = []
    r = pool.submit(lambda: done.append(1))
    assert isinstance(r, Result)
    assert r.success is True


def test_submit_result_after_shutdown_completes_with_exception() -> None:
    # Deterministic rejection: after shutdown the pool KNOWS the task will
    # never run, so the handle must complete with an exception — not hang.
    p = ThreadPoolWorker(min_workers=1, max_workers=2)
    p.shutdown(wait=True, timeout=5)
    handle = p.submit_result(lambda: 1)
    with pytest.raises(RuntimeError, match="shut down"):
        handle.result(timeout=5)
    assert handle.done() is True


def test_submit_result_evicted_completes_with_exception() -> None:
    # Backpressure eviction: the oldest queued task is dropped; its handle
    # must complete with an exception so its owner never blocks forever.
    import threading
    import time

    release = threading.Event()
    p = ThreadPoolWorker(min_workers=1, max_workers=1, queue_size=1)
    try:
        # Occupy the only worker so the queue fills instead of being drained.
        p.submit_result(lambda: release.wait(timeout=10))
        time.sleep(0.2)  # let the worker pick up the blocking task

        # Fill the queue (capacity 1).
        dropped = p.submit_result(lambda: 1)
        # Submit one more -> FIFO eviction drops `dropped` (the oldest queued).
        accepted = p.submit_result(lambda: 2)

        # The dropped handle must complete with an exception, not hang.
        with pytest.raises(RuntimeError, match="evicted"):
            dropped.result(timeout=5)
        assert dropped.done() is True

        # The accepted task still runs once the worker frees up.
        release.set()
        assert accepted.result(timeout=5) == 2
    finally:
        release.set()
        p.shutdown(wait=True, timeout=5)


def test_task_handle_timeout_before_completion() -> None:
    handle = TaskHandle()  # never completed
    with pytest.raises(TimeoutError):
        handle.result(timeout=0.05)
    assert handle.done() is False


def test_default_submit_result_not_implemented() -> None:
    class BareWorker(WorkerPort):
        def submit(self, fn, *a, **k):  # type: ignore[no-untyped-def]
            return Result.ok()

        def shutdown(self, wait=True, timeout=None):  # type: ignore[no-untyped-def]
            return Result.ok()

        def stats(self) -> dict:
            return {}

    with pytest.raises(NotImplementedError):
        BareWorker().submit_result(lambda: None)
