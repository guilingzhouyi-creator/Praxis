"""Tests for the code-format tool handlers (_format.py).

Covers format_file / format_project thin wrappers over
l3.services.code_format: required-arg validation and delegate forwarding.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "systems/python-reference-runtime"))

from unittest.mock import patch

from l3.tools._format import format_file, format_project


class TestFormatFile:
    """Test suite for format_file."""

    def test_missing_path(self):
        """format_file without path returns a validation error."""
        result = format_file({}, "agent-1")
        assert result["success"] is False
        assert "path is required" in result["error"]

    def test_delegates_to_engine(self):
        """format_file forwards path/tool to code_format.format_file."""
        with patch("l3.tools._format._format_file", return_value={"success": True, "changed": False}) as mock:
            result = format_file({"path": "systems/python-reference-runtime/x.py", "tool": "ruff"}, "agent-1")
        mock.assert_called_once_with("systems/python-reference-runtime/x.py", tool="ruff")
        assert result["success"] is True

    def test_delegates_empty_tool(self):
        """format_file with no tool override forwards an empty tool string."""
        with patch("l3.tools._format._format_file", return_value={"success": True, "changed": True}) as mock:
            result = format_file({"path": "systems/python-reference-runtime/y.py"}, "agent-1")
        mock.assert_called_once_with("systems/python-reference-runtime/y.py", tool="")
        assert result["success"] is True


class TestFormatProject:
    """Test suite for format_project."""

    def test_default_root(self):
        """format_project defaults to the current directory."""
        with patch(
            "l3.tools._format._format_project", return_value={"success": True, "total": 0, "changed": 0}
        ) as mock:
            result = format_project({}, "agent-1")
        mock.assert_called_once_with(root=".", tool="")
        assert result["success"] is True

    def test_custom_root(self):
        """format_project forwards path/tool to the engine."""
        with patch(
            "l3.tools._format._format_project", return_value={"success": True, "total": 2, "changed": 1}
        ) as mock:
            result = format_project({"path": "systems/python-reference-runtime/l1", "tool": "ruff"}, "agent-1")
        mock.assert_called_once_with(root="systems/python-reference-runtime/l1", tool="ruff")
        assert result["success"] is True
        assert result["changed"] == 1

    def test_engine_error_propagates(self):
        """format_project surfaces engine failures."""
        with patch("l3.tools._format._format_project", return_value={"success": False, "error": "no files"}):
            result = format_project({"path": "."}, "agent-1")
        assert result["success"] is False
        assert "no files" in result["error"]
