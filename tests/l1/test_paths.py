"""Tests for platform-aware deployment path resolution."""

from __future__ import annotations

import threading
from pathlib import Path

import l1.kernel.paths as paths


def test_cli_project_preserves_workspace_config_path() -> None:
    resolved = paths.PraxisPaths(paths.DeployMode.CLI_PROJECT)

    assert resolved.data_dir == ".praxis"
    assert resolved.config_file == "config/praxis.yaml"


def test_windows_package_mode_uses_appdata_for_data_and_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(paths, "IS_MAC", False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    resolved = paths.PraxisPaths(paths.DeployMode.PIP_PACKAGE)

    expected_dir = str(tmp_path / "praxis")
    assert resolved.data_dir == expected_dir
    assert resolved.config_dir == expected_dir
    assert resolved.config_file == str(Path(expected_dir) / "praxis.yaml")


def test_pip_mode_config_file_respects_data_directory_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path))

    resolved = paths.PraxisPaths(paths.DeployMode.PIP_PACKAGE)

    assert resolved.data_dir == str(tmp_path)
    assert resolved.config_file == str(tmp_path / "praxis.yaml")


def test_reset_paths_reloads_environment_override(tmp_path, monkeypatch) -> None:
    """A reset makes the next singleton read the current environment."""
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    paths.reset_paths()
    try:
        monkeypatch.setenv("PRAXIS_DATA_DIR", str(first_dir))
        first = paths.get_paths()
        monkeypatch.setenv("PRAXIS_DATA_DIR", str(second_dir))
        paths.reset_paths()
        second = paths.get_paths()

        assert first.data_dir == str(first_dir)
        assert second.data_dir == str(second_dir)
        assert second is not first
    finally:
        paths.reset_paths()


def test_get_paths_refreshes_auto_detected_paths_after_environment_change(tmp_path, monkeypatch) -> None:
    paths.reset_paths()
    try:
        initial = paths.get_paths()
        data_dir = str(tmp_path / "runtime")
        monkeypatch.setenv("PRAXIS_DATA_DIR", data_dir)

        refreshed = paths.get_paths()

        assert refreshed is not initial
        assert refreshed.data_dir == data_dir
    finally:
        paths.reset_paths()


def test_get_paths_concurrent_callers_share_one_instance() -> None:
    """Concurrent initialization returns exactly one cached path set."""
    paths.reset_paths()
    callers = 8
    barrier = threading.Barrier(callers + 1)
    instances: list[paths.PraxisPaths] = []
    instances_lock = threading.Lock()

    def _get() -> None:
        barrier.wait()
        resolved = paths.get_paths()
        with instances_lock:
            instances.append(resolved)

    threads = [threading.Thread(target=_get) for _ in range(callers)]
    for worker in threads:
        worker.start()
    barrier.wait()
    for worker in threads:
        worker.join()
    try:
        assert len(instances) == callers
        assert {id(instance) for instance in instances} == {id(instances[0])}
    finally:
        paths.reset_paths()


def test_configured_paths_ignore_later_environment_changes(tmp_path, monkeypatch) -> None:
    paths.reset_paths()
    try:
        configured_data_dir = str(tmp_path / "configured")
        configured = paths.configure_paths(data_dir=configured_data_dir)
        monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path / "environment"))

        resolved = paths.get_paths()

        assert resolved is configured
        assert resolved.data_dir == configured_data_dir
    finally:
        paths.reset_paths()
