"""Validate shared deployment path vectors against the Python reference."""

from __future__ import annotations

import json
from pathlib import Path

import l1.kernel.paths as paths

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_paths_vectors.json"


def test_shared_path_vectors_match_python_reference(monkeypatch) -> None:
    """Keep core path derivation fields aligned with the Rust candidate."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for vector in vectors:
        monkeypatch.delenv("PRAXIS_DATA_DIR", raising=False)
        monkeypatch.delenv("PRAXIS_CONFIG_DIR", raising=False)
        monkeypatch.delenv("PRAXIS_SKILL_DIR", raising=False)
        monkeypatch.delenv("PRAXIS_INSTALL_DIR", raising=False)
        monkeypatch.delenv("PRAXIS_TEMPLATES_DIR", raising=False)
        monkeypatch.setattr(paths, "IS_WINDOWS", vector["input"]["is_windows"])
        monkeypatch.setattr(paths, "IS_MAC", vector["input"]["is_mac"])
        resolved = paths.PraxisPaths(paths.DeployMode(vector["input"]["deploy_mode"]))
        expected = vector["expected"]
        for field in (
            "data_dir",
            "config_dir",
            "config_file",
            "logs_dir",
            "skill_dirs",
            "skill_evolved_dir",
            "events_db",
            "mute_state",
            "mode_state",
            "todo_state",
            "sandbox_state",
            "todo_table",
            "sandbox_root",
            "socket_dir",
            "todo_dir",
            "cell_state_template",
            "memory_persist_ring2",
            "memory_persist_ring3",
            "sandbox_state_template",
            "snapshot_path_template",
            "skill_lean_case_template",
            "agent_session_template",
        ):
            assert getattr(resolved, field) == expected[field], (vector["case"], field)
