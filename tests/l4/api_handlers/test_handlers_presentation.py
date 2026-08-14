"""API handler: tool presentation mode tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestPresentationHandlers:
    def test_importable(self):
        from l4.api_handlers.api_handlers_security import (
            presentation_mode_get,
            presentation_mode_set,
        )

        assert callable(presentation_mode_get)
        assert callable(presentation_mode_set)

    def test_get_returns_status(self):
        from l3.tool_system.tool_presentation import reset_presentation_mode
        from l4.api_handlers.api_handlers_security import presentation_mode_get

        try:
            status = presentation_mode_get()
            assert status["mode"] in ("native", "code", "both")
            assert "python" in status["languages"]
        finally:
            reset_presentation_mode()

    def test_set_switches_mode(self):
        from l3.tool_system.tool_presentation import reset_presentation_mode
        from l4.api_handlers.api_handlers_security import (
            presentation_mode_get,
            presentation_mode_set,
        )

        try:
            result = presentation_mode_set({"mode": "code"})
            assert result["success"] is True
            assert result["mode"] == "code"
            assert presentation_mode_get()["mode"] == "code"
        finally:
            reset_presentation_mode()

    def test_set_invalid_rejected(self):
        from l4.api_handlers.api_handlers_security import presentation_mode_set

        result = presentation_mode_set({"mode": "bogus"})
        assert result["success"] is False
