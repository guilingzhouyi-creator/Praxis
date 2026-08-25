"""Canonical /intent and /scout command tests (single /-command surface)."""

from __future__ import annotations

import pytest

from l2.commands import get_command, get_handler
from l2.l2_shell import dispatch
from l2.shells.session import ShellSession
from l2.shells.terminal import intent_direct, scout_commission


@pytest.fixture
def session() -> ShellSession:
    """A fresh per-session shell state."""
    return ShellSession(shell="test", session_id="direct-cmd")


def test_commands_registered() -> None:
    """/intent and /scout are registered engine commands with handlers."""
    assert get_command("intent") is not None
    assert get_handler("intent") is not None
    assert get_command("scout") is not None
    assert get_handler("scout") is not None


def test_intent_requires_text(session: ShellSession) -> None:
    """/intent without text returns a usage error."""
    result = dispatch("/intent", session)
    assert result.get("success") is False
    assert "usage" in result.get("error", "")


def test_scout_requires_task(session: ShellSession) -> None:
    """/scout without a task returns a usage error."""
    result = dispatch("/scout", session)
    assert result.get("success") is False
    assert "usage" in result.get("error", "")


def test_intent_result_shape(session: ShellSession) -> None:
    """/intent returns the canonical intent dict shape (fail-closed without boot)."""
    result = dispatch("/intent hello", session)
    assert result.get("type") == "intent"
    assert result.get("intent") == "hello"
    assert "error" in result


def test_scout_result_shape(session: ShellSession) -> None:
    """/scout returns the canonical scout dict shape (fail-closed without boot)."""
    result = dispatch("/scout investigate", session)
    assert result.get("type") == "scout"
    assert "error" in result


def test_intent_routed_to_agent(session: ShellSession) -> None:
    """/intent text@cell/agent routes to the named agent."""
    result = dispatch("/intent hello@cell-1/agent-2", session)
    assert result.get("type") == "intent"
    assert result.get("intent") == "hello"


def test_shared_functions_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    """intent_direct returns the shape directly (no terminal required)."""
    result = intent_direct("task", "agent-1")
    assert result.get("type") == "intent"
    assert result.get("intent") == "task"


def test_shared_scout_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """scout_commission rejects an empty task."""
    result = scout_commission("", "agent-1", "cell-1")
    assert result.get("success") is False
    assert "usage" in result.get("error", "")
