"""Shell family tests — registry, bindings, config-driven instantiation."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestShellFamily:
    def test_empty_family(self):
        from l2.shells.family import get_family, reset_family

        reset_family()
        family = get_family()
        assert family.list() == []
        assert family.revision() == 0

    def test_register_get_list(self):
        from l2.shells.family import ShellFamily
        from l2.shells.terminal import TerminalShell

        family = ShellFamily()
        shell = TerminalShell()
        family.register(shell, bindings=["cli"])
        assert family.list() == ["terminal"]
        assert family.get("terminal") is shell
        assert family.default() is shell
        assert family.resolve("cli") is shell

    def test_revision_bumps(self):
        from l2.shells.family import ShellFamily
        from l2.shells.terminal import TerminalShell

        family = ShellFamily()
        r0 = family.revision()
        family.register(TerminalShell())
        assert family.revision() > r0

    def test_register_rejects_unnamed(self):
        from l2.shells.base import Shell
        from l2.shells.family import ShellFamily

        class NoName(Shell):
            def run(self, text, session=None):
                return {}

        family = ShellFamily()
        try:
            family.register(NoName())
            raised = False
        except ValueError:
            raised = True
        assert raised

    def test_load_config_instantiates(self):
        from l2.shells.family import ShellFamily

        family = ShellFamily()
        cfg = {
            "enabled": True,
            "default": "terminal",
            "shells": {"terminal": {"module": "l2.shells.terminal", "class": "TerminalShell"}},
            "bindings": {"tty": "terminal"},
        }
        count = family.load_config(cfg)
        assert count == 1
        assert family.resolve("tty").name == "terminal"
        assert family.default().name == "terminal"

    def test_load_config_disabled(self):
        from l2.shells.family import ShellFamily

        family = ShellFamily()
        cfg = {"enabled": False, "shells": {"terminal": {"module": "l2.shells.terminal", "class": "TerminalShell"}}}
        assert family.load_config(cfg) == 0
        assert family.list() == []

    def test_load_config_bad_spec_skipped(self):
        from l2.shells.family import ShellFamily

        family = ShellFamily()
        cfg = {"enabled": True, "shells": {"broken": {"module": "no.such.module", "class": "X"}}}
        assert family.load_config(cfg) == 0
        assert family.list() == []

    def test_snapshot(self):
        from l2.shells.family import ShellFamily
        from l2.shells.terminal import TerminalShell

        family = ShellFamily()
        family.register(TerminalShell(), bindings=["cli"])
        snap = family.snapshot()
        assert "terminal" in snap["shells"]
        assert snap["bindings"] == {"cli": "terminal"}
        assert snap["default"] == "terminal"

    def test_bind_unknown_raises(self):
        from l2.shells.family import ShellFamily

        family = ShellFamily()
        try:
            family.bind("x", "nosuch")
            raised = False
        except KeyError:
            raised = True
        assert raised
