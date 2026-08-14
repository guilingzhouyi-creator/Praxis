"""Boot/shutdown lifecycle roundtrip — memories as the OS root filesystem.

shutdown_to_memories() dumps runtime state into memories/ and recompiles
the catalog; init_from_memories() reloads agent config from the latest
snapshot. Runs against a temp memories dir so the real repo memories/
is never touched.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def _temp_memories(tmp_path, monkeypatch):
    """Point memory_init at a temp memories dir (isolated from the repo)."""
    import l3.memory.memory_init as mi

    monkeypatch.setattr(mi, "MEMORIES_DIR", tmp_path)
    monkeypatch.setattr(mi, "AGENT_SESSIONS_DIR", tmp_path / "AGENT" / "sessions")
    monkeypatch.setattr(mi, "OPS_DIR", tmp_path / "ops")
    monkeypatch.setattr(mi, "PHASE_DIR", tmp_path / "PHASE")
    monkeypatch.setattr(mi, "DSL_DIR", tmp_path / "dsl")
    monkeypatch.setattr(mi, "COMPILER_PATH", tmp_path / "dsl" / "compiler.py")
    monkeypatch.setattr(mi, "_SHUTDOWN_IN_PROGRESS", False)
    return tmp_path


class TestShutdownToMemories:
    """shutdown_to_memories must run end-to-end and report each step."""

    def test_shutdown_returns_step_report(self, _temp_memories):
        from l3.memory.memory_init import shutdown_to_memories

        result = shutdown_to_memories()
        assert isinstance(result, dict)
        # The DSL compiler step must be reported even when the compiler
        # script does not exist ("not_found") — never missing.
        assert "compiler" in result["results"]


class TestInitFromMemories:
    """init_from_memories must run without crashing on an empty dir."""

    def test_init_runs_without_snapshots(self, _temp_memories):
        from l3.memory.memory_init import init_from_memories

        result = init_from_memories()
        assert isinstance(result, dict)
