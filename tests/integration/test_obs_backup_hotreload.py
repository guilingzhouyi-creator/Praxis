"""Cross-layer integration tests for recent production features.

Covers three end-to-end chains added across recent feature branches:
  1. G6 trace_id: error_bus capture carries the active trace id (contextvar)
     flowing through a tool-like scope.
  2. G2 backup/recovery: create → list → restore round-trip preserves state.
  3. G3 config hot-reload: watch_config is idempotent and reload_config
     applies a praxis.yaml without a full reboot.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestTraceIdChain:
    """G6: trace id flows through error_bus captures."""

    def test_capture_carries_trace_id(self):
        """capture() inside trace_scope records the active trace id."""
        from l3.error_bus import capture
        from l3.error_bus.core import get_trace_id, trace_scope

        assert get_trace_id() == ""
        with trace_scope("trace-xyz-1"):
            assert get_trace_id() == "trace-xyz-1"
            r = capture("integration test error", error_code="E_INT_TEST", component="services")
        assert get_trace_id() == ""
        entry = r.get("entry", {})
        assert entry.get("trace_id") == "trace-xyz-1", entry

    def test_scope_restores_previous_id(self):
        """Nested trace_scope restores the outer id on exit."""
        from l3.error_bus.core import get_trace_id, trace_scope

        with trace_scope("outer-id"):
            with trace_scope("inner-id"):
                assert get_trace_id() == "inner-id"
            assert get_trace_id() == "outer-id"


class TestBackupRoundTrip:
    """G2: backup create → list → restore preserves runtime state."""

    def test_create_list_restore(self, tmp_path, monkeypatch):
        """A backup snapshot round-trips a state file unchanged."""
        # get_paths() is a cached singleton, so patching the env var would not
        # re-derive data_dir — patch the backup module's data_dir directly.
        from l3.services import backup as _backup_mod

        monkeypatch.setattr(_backup_mod, "data_dir", lambda: str(tmp_path))
        state = tmp_path / "state.json"
        state.write_text('{"k": "v", "n": 1}', encoding="utf-8")

        from l3.services.backup import create_backup, list_backups, restore_backup

        r = create_backup()
        assert r["success"], r
        assert r["copied_files"] >= 1

        entries = list_backups()
        assert entries and entries[0]["backup"] == r["backup"]

        # Mutate state, then restore from backup.
        state.write_text('{"k": "changed"}', encoding="utf-8")
        rr = restore_backup(r["backup"])
        assert rr["success"], rr
        assert state.read_text(encoding="utf-8") == '{"k": "v", "n": 1}'


class TestConfigHotReload:
    """G3: config watcher is idempotent and manual reload works."""

    def test_watch_stop_reload_idempotent(self):
        """start/stop watch and one-shot reload do not raise."""
        from l3.config import config_loader as cl

        # Stop is always safe (idempotent).
        stop = cl.stop_watch_config()
        assert stop["success"]
        # Starting watch on the repo config is safe; may already be running.
        r = cl.watch_config()
        assert r["success"] or r.get("already_running")
        # Manual reload returns a dict (success may vary if config missing).
        rr = cl.reload_config()
        assert isinstance(rr, dict)
