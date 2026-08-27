"""Scout — scout agent tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "systems/python-reference-runtime"))


class TestScout:
    def test_get_pool_importable(self):
        from l3.agent.scout import get_pool

        assert callable(get_pool)

    def test_scout_cache_clear_importable(self):
        from l3.agent.scout import scout_cache_clear

        assert callable(scout_cache_clear)

    def test_stop_shuts_down_executor(self):
        """Regression: ScoutPool.stop() must shut down the executor.

        Executor threads are non-daemon — without shutdown they would block
        interpreter exit and accumulate across pool rebuilds (reset_pool).
        """
        import pytest

        from l3.agent.scout import get_pool, reset_pool

        reset_pool()
        pool = get_pool()
        assert pool._executor._shutdown is False
        pool.stop()
        # Submitting after stop must raise: proves shutdown() ran.
        with pytest.raises(RuntimeError):
            pool._executor.submit(lambda: None)
        # stop() is idempotent and reset_pool() must not raise either.
        pool.stop()
        reset_pool()
