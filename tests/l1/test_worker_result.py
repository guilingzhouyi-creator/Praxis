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
