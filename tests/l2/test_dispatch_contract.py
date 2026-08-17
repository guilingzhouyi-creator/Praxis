"""Dispatch JSON contract pins — every render-ready result must be JSON-safe.

These tests freeze the stable parts of the L2 dispatch surface so the
TypeScript port can consume identical shapes. They deliberately exercise
only commands that do not depend on a booted L3 runtime (pure shell
built-ins); the payload must always survive json.dumps (no bytes, no
objects, no non-string keys).
"""

from __future__ import annotations

import json

import pytest

from l2.l2_shell import dispatch
from l2.shells.session import ShellSession


@pytest.fixture
def session() -> ShellSession:
    """A fresh per-session shell state (no global fallback pollution)."""
    return ShellSession(shell="test", session_id="contract")


def _assert_json_safe(result: dict) -> None:
    """Assert the result is a dict and survives canonical JSON serialization."""
    assert isinstance(result, dict)
    dumped = json.dumps(result, ensure_ascii=False)
    assert json.loads(dumped) == result


@pytest.mark.parametrize(
    "line",
    [
        "/help",
        "/lang",
        "/history",
        "/sysinfo",
        "/help status",
    ],
)
def test_builtin_results_are_json_safe(session: ShellSession, line: str) -> None:
    """Pure shell built-ins return JSON-safe dicts with success=True."""
    result = dispatch(line, session)
    _assert_json_safe(result)
    assert result.get("success") is True


def test_unknown_command_shape(session: ShellSession) -> None:
    """The unknown-command error shape is stable (success/error/suggestions)."""
    result = dispatch("/definitely-not-a-command-xyz", session)
    _assert_json_safe(result)
    assert result.get("success") is False
    assert "error" in result
    assert isinstance(result.get("suggestions"), list)


def test_pipeline_result_is_json_safe(session: ShellSession) -> None:
    """The pipeline wrapper returns a JSON-safe dict (even for stubs)."""
    result = dispatch("/help | /lang", session)
    _assert_json_safe(result)


def test_alias_resolution_shape(session: ShellSession) -> None:
    """Aliased commands resolve to the same JSON-safe contract."""
    result = dispatch("/h", session)
    _assert_json_safe(result)
