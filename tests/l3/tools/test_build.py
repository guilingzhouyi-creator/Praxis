"""Tests for build/test tool handlers."""

from __future__ import annotations

import l3.tools._build as _build


def _no_toolchain_run(args, **kwargs):
    """Simulate "no such build toolchain" — avoids executing real build/test
    commands in the repo root when no path is provided."""
    raise FileNotFoundError("no such toolchain")


class _NoToolchainPort:
    """Minimal process fake that makes every detector unavailable."""

    def run_args(self, args, **kwargs):
        """Raise the legacy no-toolchain error for the build handler."""
        return _no_toolchain_run(args, **kwargs)


class TestBuildProject:
    def test_no_path(self, monkeypatch):
        monkeypatch.setattr(_build, "get_process_port", lambda: _NoToolchainPort())
        r = _build.build_project({}, "agent-a")
        assert isinstance(r, dict)
        assert "success" in r

    def test_nonexistent_dir(self):
        r = _build.build_project({"path": "/nonexistent_build_dir"}, "agent-a")
        assert not r["success"]
        assert "no supported" in r.get("error", "").lower() or "not found" in r.get("error", "").lower()


class TestTestProject:
    def test_no_path(self, monkeypatch):
        monkeypatch.setattr(_build, "get_process_port", lambda: _NoToolchainPort())
        r = _build.test_project({}, "agent-a")
        assert isinstance(r, dict)
        assert "success" in r

    def test_nonexistent_dir(self):
        r = _build.test_project({"path": "/nonexistent_test_dir"}, "agent-a")
        assert not r["success"]


class TestDeploy:
    def test_basic(self):
        r = _build.deploy({"target": "production"}, "agent-a")
        assert isinstance(r, dict)

    def test_no_target(self):
        r = _build.deploy({}, "agent-a")
        assert isinstance(r, dict)


class TestDbMigrate:
    def test_basic(self):
        r = _build.db_migrate({"migration": "v002"}, "agent-a")
        assert isinstance(r, dict)

    def test_no_migration(self):
        r = _build.db_migrate({}, "agent-a")
        assert isinstance(r, dict)


class TestRollback:
    def test_basic(self):
        r = _build.rollback({"version": "v1"}, "agent-a")
        assert isinstance(r, dict)

    def test_no_version(self):
        r = _build.rollback({}, "agent-a")
        assert isinstance(r, dict)
