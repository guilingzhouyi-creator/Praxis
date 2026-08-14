"""L2 Shell: tool presentation command tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestPresentationCommand:
    def test_status_default(self):
        from l2.l2_shell.commands.presentation import _cmd_presentation
        from l3.tool_system.tool_presentation import reset_presentation_mode

        try:
            result = _cmd_presentation([])
            assert result["success"] is True
            assert result["mode"] in ("native", "code", "both")
        finally:
            reset_presentation_mode()

    def test_switch_to_code(self):
        from l2.l2_shell.commands.presentation import _cmd_presentation
        from l3.tool_system.tool_presentation import reset_presentation_mode

        try:
            result = _cmd_presentation(["code"])
            assert result["success"] is True
            assert result["mode"] == "code"
        finally:
            reset_presentation_mode()

    def test_invalid_rejected(self):
        from l2.l2_shell.commands.presentation import _cmd_presentation

        result = _cmd_presentation(["bogus"])
        assert result["success"] is False

    def test_reset(self):
        from l2.l2_shell.commands.presentation import _cmd_presentation
        from l3.tool_system.tool_presentation import get_presentation_mode, reset_presentation_mode

        try:
            _cmd_presentation(["code"])
            _cmd_presentation(["reset"])
            assert get_presentation_mode() == "native"
        finally:
            reset_presentation_mode()
