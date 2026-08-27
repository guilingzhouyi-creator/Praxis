"""API shell handlers — /api/v2/shell dispatch, autocomplete, commands.

Covers the three endpoints wired by frontend-kernel-roadmap Phase 1–3:
  POST /api/v2/shell                → _shell_dispatch
  GET  /api/v2/shell/autocomplete   → _shell_autocomplete
  GET  /api/v2/shell/commands       → _shell_commands
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "systems/python-reference-runtime"))


class TestShellDispatch:
    """POST /api/v2/shell — one input line through the L2 engine."""

    def test_missing_text(self):
        from l4.api_handlers.api_handlers_agent import _shell_dispatch

        r = _shell_dispatch({})
        assert r.get("success") is False
        assert "text" in r.get("error", "")

    def test_engine_command_dispatch(self):
        from l4.api_handlers.api_handlers_agent import _shell_dispatch

        r = _shell_dispatch({"text": "/help"})
        assert r.get("success") is True
        # /help renders a table result: either an output string or structured
        # keys — never a bare failure.
        assert r.get("output") is not None or r.get("commands") is not None or "type" in r

    def test_dispatch_with_session(self):
        from l4.api_handlers.api_handlers_agent import _shell_dispatch

        r = _shell_dispatch({"text": "/help", "session": {"shell": "terminal", "session_id": "s-1"}})
        assert r.get("success") is True

    def test_dispatch_non_text_body(self):
        from l4.api_handlers.api_handlers_agent import _shell_dispatch

        r = _shell_dispatch({"text": 123})
        assert r.get("success") is False or r.get("type") is not None


class TestShellAutocomplete:
    """GET /api/v2/shell/autocomplete — partial-line suggestions."""

    def test_autocomplete_commands(self):
        from l4.api_handlers.api_handlers_agent import _shell_autocomplete

        r = _shell_autocomplete({"text": "/"})
        assert r.get("success") is True
        assert isinstance(r.get("suggestions", []), list)

    def test_autocomplete_prefix(self):
        from l4.api_handlers.api_handlers_agent import _shell_autocomplete

        r = _shell_autocomplete({"text": "/he"})
        assert r.get("success") is True
        assert isinstance(r.get("suggestions", []), list)

    def test_autocomplete_empty_text(self):
        from l4.api_handlers.api_handlers_agent import _shell_autocomplete

        r = _shell_autocomplete({})
        assert r.get("success") is True
        assert isinstance(r.get("suggestions", []), list)


class TestShellCommands:
    """GET /api/v2/shell/commands — available command list."""

    def test_commands_non_empty(self):
        from l4.api_handlers.api_handlers_agent import _shell_commands

        r = _shell_commands({})
        assert r.get("success") is True
        assert isinstance(r.get("commands", []), list)
        assert len(r.get("commands", [])) > 0

    def test_commands_entries_have_name(self):
        from l4.api_handlers.api_handlers_agent import _shell_commands

        r = _shell_commands({})
        for cmd in r.get("commands", []):
            assert cmd.get("name"), f"command entry missing name: {cmd}"

    def test_commands_category_filter(self):
        from l4.api_handlers.api_handlers_agent import _shell_commands

        r = _shell_commands({"category": "system"})
        assert r.get("success") is True
        for cmd in r.get("commands", []):
            assert cmd.get("category") == "system"
