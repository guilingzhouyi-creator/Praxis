"""Cron scheduler tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCronScheduler:
    def test_importable(self):
        from l4.cron_scheduler import CronScheduler

        assert callable(CronScheduler)

    def test_add_default_cell_from_params(self):
        """Empty cell_id resolves to the config-driven DEFAULT_CELL_ID."""
        from l1.kernel.params.agent import DEFAULT_CELL_ID
        from l4.cron_scheduler import CronScheduler

        sched = CronScheduler()
        r = sched.add("c1", "0 * * * *", "run sync", domain="app")
        assert r.get("success") is True
        entries = sched.list()
        entry = next((e for e in entries if e["id"] == "c1"), None)
        assert entry is not None
        assert entry.get("cell_id") == DEFAULT_CELL_ID

    def test_add_explicit_cell_kept(self):
        """An explicit cell_id is never overridden."""
        from l4.cron_scheduler import CronScheduler

        sched = CronScheduler()
        r = sched.add("c2", "0 * * * *", "run sync", domain="app", cell_id="cell-9")
        assert r.get("success") is True
        entries = sched.list()
        entry = next((e for e in entries if e["id"] == "c2"), None)
        assert entry is not None
        assert entry.get("cell_id") == "cell-9"
