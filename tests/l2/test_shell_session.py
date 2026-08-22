"""ShellSession tests — per-session state model (shell family)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestShellSession:
    def test_default_state(self):
        from l2.shells.session import ShellSession

        s = ShellSession(shell="terminal")
        assert s.mode == "L3A"
        assert s.cell_id == "cell-1"
        assert s.agent_id == ""
        assert not s.is_direct()

    def test_switch_to_direct(self):
        from l2.shells.session import ShellSession

        s = ShellSession()
        s.switch_to_direct("cell-x", "agent-42", "sess-1")
        assert s.mode == "DIRECT"
        assert s.cell_id == "cell-x"
        assert s.agent_id == "agent-42"
        assert s.session_id == "sess-1"
        assert s.is_direct()

    def test_switch_to_direct_no_session_id(self):
        from l2.shells.session import ShellSession

        s = ShellSession()
        s.switch_to_direct("cell-2", "agent-7")
        assert s.is_direct()
        assert s.session_id == ""

    def test_switch_to_l3a_clears_state(self):
        from l2.shells.session import ShellSession

        s = ShellSession()
        s.switch_to_direct("cell-x", "agent-42", "sess-1")
        s.switch_to_l3a()
        assert s.mode == "L3A"
        assert s.agent_id == ""
        assert s.session_id == ""
        assert not s.is_direct()

    def test_direct_requires_agent(self):
        from l2.shells.session import ShellSession

        s = ShellSession()
        s.mode = "DIRECT"
        assert not s.is_direct()

    def test_sessions_are_isolated(self):
        from l2.shells.session import ShellSession

        a = ShellSession(shell="terminal", session_id="a")
        b = ShellSession(shell="terminal", session_id="b")
        a.switch_to_direct("cell-x", "agent-1")
        assert not b.is_direct()
        assert b.mode == "L3A"
        assert b.agent_id == ""

    def test_as_dict(self):
        from l2.shells.session import ShellSession

        s = ShellSession(shell="terminal", session_id="s1")
        s.switch_to_direct("cell-x", "agent-9", "s2")
        snap = s.as_dict()
        assert snap["shell"] == "terminal"
        assert snap["mode"] == "DIRECT"
        assert snap["cell_id"] == "cell-x"
        assert snap["agent_id"] == "agent-9"
        assert snap["session_id"] == "s2"
