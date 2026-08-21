"""Tests for Git tool handlers."""

from __future__ import annotations

import subprocess

from l3.tools._git import (
    git_branch,
    git_commit,
    git_push,
)


def _guard_no_real_commit() -> None:
    try:
        r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip() == "true":
            import pytest

            pytest.skip("inside git repo — skip to prevent accidental commit")
    except Exception:
        pass


def _hermetic_push_repo(tmp_path, monkeypatch):
    """Set up a temp push repo (local bare remote, no network) and chdir into it.

    The suite runs inside a git worktree; a real ``git push`` would hit the
    praxis remotes and wait on a network handshake (measured 11.6s in the
    full run). Chdir'ing into a tmp repo makes ``_git(["push"])`` target a
    local bare remote — fast and hermetic.
    """
    bare = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    # Hermetic identity/global config so nothing from the real user config leaks.
    subprocess.run(["git", "config", "user.email", "test@praxis.local"], check=True, cwd=work)
    subprocess.run(["git", "config", "user.name", "Praxis Test"], check=True, cwd=work)
    no_hooks = tmp_path / "no-hooks"
    no_hooks.mkdir()
    subprocess.run(["git", "config", "core.hooksPath", str(no_hooks)], check=True, cwd=work)
    (work / "init.txt").write_text("init")
    subprocess.run(["git", "add", "-A"], check=True, cwd=work)
    subprocess.run(["git", "commit", "-q", "-m", "init"], check=True, cwd=work)
    # First real push to the local bare remote establishes origin/main upstream.
    subprocess.run(["git", "remote", "add", "origin", str(bare)], check=True, cwd=work)
    subprocess.run(["git", "push", "-u", "origin", "main"], check=True, cwd=work)
    # One more commit so a follow-up push has something to move.
    (work / "second.txt").write_text("second")
    subprocess.run(["git", "add", "-A"], check=True, cwd=work)
    subprocess.run(["git", "commit", "-q", "-m", "second"], check=True, cwd=work)
    monkeypatch.chdir(work)


class TestGitCommit:
    def test_no_message(self):
        r = git_commit({}, "agent-a")
        assert not r["success"]
        assert "message is required" in r["error"]

    def test_with_message(self):
        _guard_no_real_commit()
        r = git_commit({"message": "test commit"}, "agent-a")
        assert isinstance(r, dict)
        assert "success" in r


class TestGitPush:
    def test_push(self, tmp_path, monkeypatch):
        _hermetic_push_repo(tmp_path, monkeypatch)
        r = git_push({}, "agent-a")
        assert isinstance(r, dict)
        assert r.get("success") is True, r.get("error", r)


class TestGitBranch:
    def test_no_action(self):
        r = git_branch({}, "agent-a")
        assert not r["success"]

    def test_list(self):
        r = git_branch({"action": "list"}, "agent-a")
        assert isinstance(r, dict)

    def test_create_no_name(self):
        r = git_branch({"action": "create"}, "agent-a")
        assert not r["success"]

    def test_switch_no_name(self):
        r = git_branch({"action": "switch"}, "agent-a")
        assert not r["success"]

    def test_delete_no_name(self):
        r = git_branch({"action": "delete"}, "agent-a")
        assert not r["success"]

    def test_invalid_action(self):
        r = git_branch({"action": "nonexistent"}, "agent-a")
        assert not r["success"]
