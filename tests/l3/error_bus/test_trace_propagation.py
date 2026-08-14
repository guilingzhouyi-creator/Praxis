"""Tests for trace_id cross-thread propagation via propagate_context."""

from __future__ import annotations

import threading
import time


class TestPropagateContext:
    """propagate_context — contextvars propagation across threads."""

    def test_thread_inherits_trace_id(self):
        from l3.error_bus.core import get_trace_id, propagate_context, set_trace_id

        set_trace_id("trace-abc")
        seen: dict = {}

        def _target() -> None:
            seen["tid"] = get_trace_id()

        t = threading.Thread(target=propagate_context(_target))
        t.start()
        t.join(timeout=5)
        set_trace_id("")
        assert seen["tid"] == "trace-abc"

    def test_wrapped_fn_keeps_arguments(self):
        from l3.error_bus.core import propagate_context

        wrapped = propagate_context(lambda a, b: a + b)
        assert wrapped(2, 3) == 5

    def test_worker_pool_submit_propagates_trace(self):
        from l3._pool import WorkerPool
        from l3.error_bus.core import get_trace_id, set_trace_id

        pool = WorkerPool(size=1)
        result: dict = {}

        def _work() -> None:
            result["tid"] = get_trace_id()

        try:
            set_trace_id("pool-trace")
            pool.submit("t1", _work)
            deadline = time.time() + 10.0
            while "tid" not in result and time.time() < deadline:
                time.sleep(0.01)
        finally:
            set_trace_id("")
            pool.shutdown()
        assert result["tid"] == "pool-trace"
