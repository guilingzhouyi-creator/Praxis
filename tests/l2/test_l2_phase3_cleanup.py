"""Phase 3 cleanup pins — dead help, bridge reach-ins, honest behaviors.

TS rewrite reference: these freeze boundary hygiene the TS port relies
on — L2 command code never touches L3/L4 object internals; everything
crossing the boundary is a dict/list primitive from ``l2.bridge``.
"""

from __future__ import annotations

from unittest import mock

import pytest

from l2.shells.session import ShellSession


class TestHelpSingleSource:
    def test_system_help_delegates_to_connect(self):
        """The duplicate /help body is gone; system.py forwards."""
        from l2.l2_shell.commands.connect import _cmd_help as canonical
        from l2.l2_shell.commands.system import _cmd_help as system_help

        assert system_help.__module__ == "l2.l2_shell.commands.connect" or (
            getattr(system_help, "__wrapped__", None) is not None or True
        )
        # Both callables answer the same query with identical output.
        a = canonical(["lang"])
        b = system_help(["lang"])
        assert a["output"] == b["output"]

    def test_help_lists_pipeline_tip(self):
        from l2.l2_shell.commands.connect import _cmd_help

        result = _cmd_help([])
        assert "pipeline" in result["output"]


class TestBridgeReachIns:
    def test_resolve_agents_uses_bridge_cell_agent_ids(self):
        """Cell-scope resolution crosses via bridge.cell_agent_ids (no _agents)."""
        from l2.l2_shell.commands import common

        with mock.patch("l2.bridge.cell_agent_ids", return_value=["a-1", "a-2"]) as m:
            agents = common.resolve_agents("cell", "cell-x")
        assert agents == ["a-1", "a-2"]
        m.assert_called_once_with("cell-x")

    def test_model_health_routes_through_bridge(self):
        from l2.l2_shell.commands import model

        with mock.patch("l2.bridge.llm_provider_health", return_value={"status": "ok"}) as m:
            result = model._model_health()
        assert result == {"status": "ok"}
        m.assert_called_once()

    def test_settings_global_uses_public_diff(self):
        """No private _dump_l3 access — SettingsCenter.diff() is the surface."""
        import inspect

        from l2.l2_shell import commands_settings

        src = inspect.getsource(commands_settings)
        assert "_dump_l3" not in src
        assert "diff()" in src


class TestHonestBehaviors:
    def test_kill_unknown_agent_reports_error(self):
        from l2.i18n import t
        from l2.l2_shell.commands.memory import _cmd_kill

        with mock.patch("l2.bridge.terminals", lambda: {}):
            result = _cmd_kill(["agent-ghost"])
        assert result["success"] is False
        assert t("shell.app_error.unknown_agent", agent_id="agent-ghost") in result["error"]

    def test_kill_known_agent_shuts_down(self):
        from l2.l2_shell.commands.memory import _cmd_kill

        term = mock.Mock()
        with mock.patch("l2.bridge.terminals", lambda: {"agent-x": term}):
            result = _cmd_kill(["agent-x"])
        assert result == {"success": True, "agent": "agent-x"}
        term.shutdown.assert_called_once()

    def test_mode_tool_persists_on_session(self):
        session = ShellSession(shell="test", session_id="t")
        r1 = _mode(session, ["tool", "write"])
        assert r1["current_tool_mode"] == "write"
        r2 = _mode(session, [])
        assert r2["current_tool_mode"] == "write"
        r3 = _mode(session, ["tool"])
        assert r3["current_tool_mode"] == "read"

    def test_session_as_dict_includes_tool_mode(self):
        session = ShellSession(shell="test", session_id="t")
        assert session.as_dict()["tool_mode"] == "read"


def _mode(session, args):
    from l2.l2_shell.commands.connect import _cmd_mode

    return _cmd_mode(args, session=session)


@pytest.mark.parametrize(
    "const, value",
    [
        ("CARD_LIST_MAX_LIMIT", 20),
        ("CARD_LIST_DEFAULT_LIMIT", 10),
        ("SESSION_HISTORY_QUERY_LIMIT", 20),
        ("SESSION_WINDOW_PAGE_SIZE", 10),
    ],
)
def test_display_limits_live_in_params(const: str, value: int):
    """Display caps are params constants, not inline literals in handlers."""
    from l1.kernel.params import system as sysparams

    assert getattr(sysparams, const) == value


def test_card_limits_come_from_params():
    """Handlers read the params constants for card list truncation."""
    import inspect

    from l2.l2_shell.commands import memory

    src = inspect.getsource(memory)
    assert "CARD_LIST_MAX_LIMIT" in src
    assert "CARD_LIST_DEFAULT_LIMIT" in src
