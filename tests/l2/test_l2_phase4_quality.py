"""Phase 4 quality pins — handler coverage for the thin dispatch surfaces.

Every test here drives a handler through mocked bridge/L1 accessors and
pins its dict contract (success/error keys, passthrough of L3 data).
These are exactly the shapes the TS dispatcher consumes, so drift here
is a wire-contract break, not just a Python3 regression.
"""

from __future__ import annotations

from unittest import mock

import pytest

# ── /session commands (commands/l3a.py) ──


class TestSessionCommands:
    def test_monitor_toggle_and_status(self):
        from l2.l2_shell.commands.l3a import _cmd_session_monitor

        with mock.patch("l2.bridge.session_monitor") as sm:
            _cmd_session_monitor(["on"])
            sm.assert_called_once_with(enabled=True)
        with mock.patch("l2.bridge.session_monitor", return_value={"status": "x"}) as sm:
            r = _cmd_session_monitor([])
            sm.assert_called_once_with()
            assert r == {"status": "x"}

    def test_reload_requires_agent(self):
        from l2.l2_shell.commands.l3a import _cmd_session_reload

        assert _cmd_session_reload([])["success"] is False
        with mock.patch("l2.bridge.auto_reload_session", return_value={"ok": 1}) as ar:
            r = _cmd_session_reload(["agent-9", "reason=drift"])
        ar.assert_called_once_with("agent-9", reason="drift")
        assert r == {"ok": 1}

    def test_history_flags(self):
        from l2.l2_shell.commands.l3a import _cmd_session_history

        with (
            mock.patch("l2.bridge.set_session_history", return_value={"switched": True}) as sh,
            mock.patch("l2.bridge.query_session_history") as q,
            mock.patch("l2.bridge.session_history_status", return_value={}),
        ):
            r = _cmd_session_history(["off"])
            sh.assert_called_once_with(enabled=False)
            assert r == {"switched": True}
            _cmd_session_history(["limit=7", "session=s-3"])
            q.assert_called_once_with(limit=7, session_id="s-3")

    def test_resume_pagination(self):
        from l2.l2_shell.commands.l3a import _cmd_session_resume

        with mock.patch("l2.bridge.load_for_window", return_value={"window": []}) as lw:
            _cmd_session_resume(["sess-1", "page=4"])
        lw.assert_called_once()
        kwargs = lw.call_args.kwargs
        assert kwargs["page"] == 4


# ── /config //cron //model (commands/model.py) ──


class TestModelCommands:
    def test_config_get_set_list(self):
        from l2.l2_shell.commands.model import _cmd_config

        with mock.patch("l1.kernel.settings.get_settings") as gs:
            gs.return_value.get.return_value = 5
            r = _cmd_config(["some.key"])
            assert r == {"success": True, "some.key": 5}
            gs.return_value.all.return_value = {}
            assert _cmd_config([]) == {"success": True, "settings": {}}

    def test_config_set_writes_through_bridge(self):
        from l2.l2_shell.commands.model import _cmd_config

        with mock.patch("l2.bridge.settings_set") as ss:
            r = _cmd_config(["set", "k", "7"])
        ss.assert_called_once()
        assert r["key"] == "k"

    def test_cron_list_add_usage(self):
        from l2.l2_shell.commands.model import _cmd_cron

        with mock.patch("l4.cron_scheduler.get_scheduler") as g:
            g.return_value.list.return_value = [{"id": "c1"}]
            assert _cmd_cron(["list"]) == {"success": True, "cron": [{"id": "c1"}]}
        r = _cmd_cron(["add", "id1", "* * * * *", "task-x"])
        assert r["success"] is True and r["id"] == "id1"
        # Bare /cron defaults to list (not an error).
        with mock.patch("l4.cron_scheduler.get_scheduler") as g:
            g.return_value.list.return_value = []
            assert _cmd_cron([])["success"] is True

    def test_model_switch_validates_role(self):
        from l2.l2_shell.commands.model import _cmd_model

        bad = _cmd_model(["switch", "ghost-role", "ollama"])
        assert bad["success"] is False

    def test_model_health_falls_back_to_providers(self):
        from l2.l2_shell.commands.model import _cmd_model

        with mock.patch("l2.bridge.llm_provider_health", return_value={}):
            with mock.patch("l2.bridge.model_providers", return_value=["p1"]):
                r = _cmd_model(["health"])
        assert r == {"success": True, "providers": ["p1"]}


# ── /history /lang /sysinfo /devices /tools /process /cache (system.py) ──


class TestSystemCommands:
    def test_history_uses_session_when_given(self):
        from l2.l2_shell.commands.system import _cmd_history

        sess = mock.Mock()
        sess.history.return_value = [{"text": "/lang"}]
        r = _cmd_history(["5"], session=sess)
        sess.history.assert_called_once_with(5)
        assert r["limit"] == 5 and len(r["history"]) == 1

    def test_history_without_session_is_empty(self):
        from l2.l2_shell.commands.system import _cmd_history

        assert _cmd_history([], session=None)["history"] == []

    def test_lang_set_and_report(self):
        from l2.l2_shell.commands.system import _cmd_lang

        with mock.patch("l2.i18n.set_locale") as sl:
            with mock.patch("l2.i18n.get_locale", return_value="zh-CN"):
                with mock.patch("l2.i18n.get_available_locales", return_value=["en"]):
                    r = _cmd_lang(["zh-CN"])
        sl.assert_called_once_with("zh-CN")
        assert r["locale"] == "zh-CN"

    def test_process_audit_branch(self):
        from l2.l2_shell.commands.system import _cmd_process

        with mock.patch("l1.kernel.process.get_table") as gt:
            gt.return_value.audit_log.return_value = [{"op": "spawn"}]
            r = _cmd_process(["audit"])
        assert r == {"success": True, "audit": [{"op": "spawn"}]}

    def test_devices_lists(self):
        from l2.l2_shell.commands.system import _cmd_devices

        with mock.patch("l1.kernel.device.get_device_manager") as gd:
            gd.return_value.list.return_value = [{"name": "cpu"}]
            r = _cmd_devices([])
        assert r["count"] == 1

    def test_tools_unknown_agent_errors(self):
        from l2.l2_shell.commands.system import _cmd_tools

        with mock.patch("l2.bridge.terminals", lambda: {}):
            r = _cmd_tools(["agent-ghost"])
        assert r["success"] is False

    def test_skills_parse_flags(self):
        from l2.l2_shell.commands.system import _parse_skill_args

        role, agent_id, rest = _parse_skill_args(["--role", "reviewer", "--agent", "a9", "get", "name"])
        assert role == "reviewer" and agent_id == "a9" and rest == ["get", "name"]

    def test_skills_unknown_subcommand(self):
        from l2.l2_shell.commands.system import _cmd_skills

        r = _cmd_skills(["definitely-not-a-sub"])
        assert r["success"] is False and "suggestions" in r

    def test_skills_get_missing_name(self):
        from l2.l2_shell.commands.system import _cmd_skills

        r = _cmd_skills(["get"])
        assert r["success"] is False


# ── TerminalShell dialect (shells/terminal.py) ──


class TestTerminalDialect:
    @pytest.fixture
    def shell(self):
        from l2.shells.terminal import TerminalShell

        return TerminalShell()

    def test_empty_line(self, shell):
        assert shell.run("") == {"success": True, "type": "empty"}

    def test_help_builtin(self, shell):
        r = shell.run("help")
        assert r["type"] == "help" and r["commands"]

    def test_system_command_via_port(self, shell):
        proc = mock.Mock(stdout="out\n", stderr="", returncode=0, timed_out=False, error_kind=None)
        with mock.patch("l2.shells.terminal.get_process_port") as gp:
            gp.return_value.run.return_value = proc
            r = shell.run("$ echo hi")
        assert r["type"] == "system" and r["output"].strip() == "out"

    def test_system_timeout_shape(self, shell):
        proc = mock.Mock(timed_out=True, stdout="", stderr="", returncode=-1, error_kind="")
        with mock.patch("l2.shells.terminal.get_process_port") as gp:
            gp.return_value.run.return_value = proc
            r = shell.run("$ slow-cmd")
        assert r == {"success": False, "type": "system", "command": "slow-cmd", "error": "timeout"}

    def test_engine_dispatch_passthrough(self, shell):
        with mock.patch("l2.l2_shell.dispatch", return_value={"success": True}) as d:
            r = shell.run("/lang", session=object())
        d.assert_called_once()
        assert r == {"success": True}

    def test_tool_call_alias_and_args(self, shell):
        spec = mock.Mock(description="read a file")
        cap = mock.Mock(return_value={"success": True, "result": {"data": {"k": "v"}}})
        with (
            mock.patch("l2.shell_completer.get_aliases", lambda: {"rf": "read_file"}),
            mock.patch("l2.bridge.get_tool", return_value=spec),
            mock.patch("l1.kernel.capability.invoke_capability", cap),
        ):
            r = shell.run("rf path=/tmp/x", session=self._session())
        assert r["type"] == "tool" and r["tool"] == "read_file"
        assert r["args"] == {"path": "/tmp/x"}

    def test_tool_unknown_reports_error(self, shell):
        with (
            mock.patch("l2.shell_completer.get_aliases", lambda: {}),
            mock.patch("l2.bridge.get_tool", return_value=None),
        ):
            r = shell.run("no-such-tool x", session=self._session())
        assert r["success"] is False and r["error"] == "unknown tool"

    def test_render_system_result(self, shell, capsys):
        shell._render({"type": "system", "output": "line1", "stderr": "", "returncode": 0})
        assert "line1" in capsys.readouterr().out

    def _session(self):
        from l2.shells.session import ShellSession

        return ShellSession(shell="terminal", session_id="t")
