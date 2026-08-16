"""Tests for shell service — session management and terminal operations."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestTerminalSession:
    def test_session_dataclass(self):
        from l2.shell_session import TerminalSession

        sess = TerminalSession(id="test-session", pid=12345)
        assert sess.id == "test-session"
        assert sess.pid == 12345
        assert not sess.is_alive()

    def test_kill_no_process(self):
        from l2.shell_session import TerminalSession

        sess = TerminalSession(id="no-proc", pid=0)
        sess.kill()


class TestTerminalManager:
    def test_create_and_list(self):
        from l2.shell_session import get_manager, reset_manager

        reset_manager()
        mgr = get_manager()
        r = mgr.create(cwd=".")
        assert r.get("success"), f"create failed: {r}"
        assert "id" in r

    def test_get_session(self):
        from l2.shell_session import get_manager, reset_manager

        reset_manager()
        mgr = get_manager()
        r = mgr.create()
        sid = r["id"]
        sess = mgr.get(sid)
        assert sess is not None
        assert sess.id == sid

    def test_get_manager_singleton(self):
        from l2.shell_session import get_manager, reset_manager

        reset_manager()
        m1 = get_manager()
        m2 = get_manager()
        assert m1 is m2

    def test_shell_helpers_import(self):
        from l2.shells.terminal import TerminalShell, direct_session, start_repl

        assert callable(direct_session)
        assert callable(start_repl)
        shell = TerminalShell()
        assert shell.name == "terminal"
        assert callable(shell.run)
        assert callable(shell.loop)

    def test_terminal_session_bound_to_l3(self):
        from l2.shells.terminal import TerminalShell

        shell = TerminalShell()
        session = shell.create_session("s-1")
        assert session.shell == "terminal"
        assert session.session_id == "s-1"
        assert session.agent_id

    def test_run_empty_line(self):
        from l2.shells.terminal import TerminalShell

        shell = TerminalShell()
        r = shell.run("   ")
        assert r.get("type") == "empty"

    def test_run_help_returns_dict(self):
        from l2.shells.terminal import TerminalShell

        shell = TerminalShell()
        r = shell.run("help")
        assert r.get("success") is True
        assert r.get("type") == "help"
        assert "commands" in r

    def test_run_unknown_tool(self):
        from l2.shells.terminal import TerminalShell

        shell = TerminalShell()
        r = shell.run("no_such_tool_xyz arg")
        assert r.get("type") == "tool"
        assert r.get("success") is False

    def test_run_tool_preserves_all_positional_args(self, monkeypatch):
        """Regression: every positional arg must reach _execute_tool_spec.

        The legacy parser dropped the LAST positional token (``elif i <
        len(parts) - 1``); multi-arg calls like ``read_file a.txt b.txt``
        silently lost ``b.txt``.
        """
        from l2.shells.terminal import TerminalShell

        captured: dict = {}

        def fake_get_tool(name):
            if name == "read_file":
                return object()
            return None

        def fake_execute(name, args, agent_id):
            captured["args"] = args
            return {"success": True, "data": "ok"}

        monkeypatch.setattr("l3.tool_system.tool_spec.get_tool", fake_get_tool)
        # W1.2: shell tools now run through invoke_gated → pipeline; patch the
        # executor binding the pipeline actually calls (tool_pipeline_steps).
        import l3.tool_system.tool_pipeline_steps as _tps

        monkeypatch.setattr(_tps, "_execute_tool_spec", fake_execute)
        monkeypatch.setattr(
            "l3.tool_system.tool_registry.TOOL_REGISTRY", {"read_file": object(), "write_file": object()}
        )
        from l1.kernel.gatechain import get_gatechain

        get_gatechain().register_tools(["read_file", "write_file"])

        shell = TerminalShell()
        r = shell.run("read_file a.txt b.txt")
        assert r.get("success") is True
        assert captured["args"] == {"arg1": "a.txt", "arg2": "b.txt"}

    def test_run_tool_mixed_kwargs_and_positional(self, monkeypatch):
        """Kwargs (``k=v``) and positional args coexist in one call."""
        from l2.shells.terminal import TerminalShell

        captured: dict = {}

        def fake_get_tool(name):
            if name == "write_file":
                return object()
            return None

        def fake_execute(name, args, agent_id):
            captured["args"] = args
            return {"success": True, "data": "ok"}

        monkeypatch.setattr("l3.tool_system.tool_spec.get_tool", fake_get_tool)
        # W1.2: shell tools now run through invoke_gated → pipeline; patch the
        # executor binding the pipeline actually calls (tool_pipeline_steps).
        import l3.tool_system.tool_pipeline_steps as _tps

        monkeypatch.setattr(_tps, "_execute_tool_spec", fake_execute)
        monkeypatch.setattr(
            "l3.tool_system.tool_registry.TOOL_REGISTRY", {"read_file": object(), "write_file": object()}
        )
        from l1.kernel.gatechain import get_gatechain

        get_gatechain().register_tools(["read_file", "write_file"])

        shell = TerminalShell()
        r = shell.run("write_file out.txt mode=w")
        assert r.get("success") is True
        assert captured["args"] == {"arg1": "out.txt", "mode": "w"}
