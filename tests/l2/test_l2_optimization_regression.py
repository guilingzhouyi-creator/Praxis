"""Regression pins for the L2 optimization pass (Phase 1 fixes).

Each test freezes one fixed defect so it cannot resurface:
  1. selector role-index domain scoring (shadowed bridge function)
  2. /settings cell/agent/pool route through l2.bridge (no phantom imports)
  3. /memory filter runs before agent resolution
  4. pipeline steps receive the session (same contract as direct dispatch)
  5. unbalanced quotes degrade to an error dict (never escape dispatch)
  6. prose containing ``|`` is not misrouted into the pipeline

TS rewrite reference: these shapes are part of the wire contract the TS
engine must reproduce — error dicts stay JSON-safe and routing decisions
(handler/alias resolution order) are identical in both languages.
"""

from __future__ import annotations

from unittest import mock

import pytest

from l2.l2_shell import _looks_like_pipeline, dispatch
from l2.shells.session import ShellSession


@pytest.fixture
def session() -> ShellSession:
    """A fresh per-session shell state (no global fallback pollution)."""
    return ShellSession(shell="test", session_id="opt-regression")


# ── Fix 1: selector shadowing ──


class TestSelectorTerritoryScoring:
    def test_multi_cell_candidates_keep_territory_scoring(self):
        """Candidates spanning two cells still score domain territory."""
        from l2 import selector

        def fake_territory(cell_id: str) -> list[str]:
            return [f"/repo/{cell_id}"]

        def fake_liveness(cell_id: str) -> dict:
            return {"agents": {f"agent-{cell_id}": {"role": "worker"}}}

        with (
            mock.patch("l2.bridge.cell_ids", lambda: ["c1", "c2"]),
            mock.patch("l2.bridge.cell_liveness", fake_liveness),
            mock.patch("l2.bridge.cell_territory", fake_territory),
        ):
            selector._rebuild_role_index(["c1", "c2"])
            result = selector.select(role="worker", domain="/repo/c2/x")
        assert result["success"] is True
        # c2's agent must win: only its territory matches the domain.
        assert result["cell_id"] == "c2"
        assert result["agent_id"] == "agent-c2"


# ── Fix 2: /settings routes through the bridge ──


class TestSettingsBridgeRouting:
    @pytest.mark.parametrize(
        "argv",
        [
            ["cell", "cell-x"],
            ["agent", "agent-x"],
            ["pool", "scout"],
            ["pool", "subagent", "cell-x"],
        ],
    )
    def test_settings_subcommands_return_dicts(self, argv):
        """Every /settings scope answers with a dict — no phantom imports."""
        from l2.l2_shell.commands_settings import _cmd_settings

        result = _cmd_settings(argv)
        assert isinstance(result, dict)
        assert "success" in result

    def test_settings_global_lists_overrides(self):
        from l2.l2_shell.commands_settings import _cmd_settings

        result = _cmd_settings(["global"])
        assert result["success"] is True
        assert isinstance(result["settings"], dict)


# ── Fix 3: /memory filter ordering ──


class TestMemoryFilterOrdering:
    def test_filter_runs_without_registered_agents(self):
        """filter dispatches before agent resolution (empty roster OK)."""
        from l2.l2_shell.commands import memory as memory_cmd

        with (
            mock.patch.object(memory_cmd, "_cmd_memory_filter", return_value={"success": True}) as mf,
            mock.patch("l2.bridge.terminals", lambda: {}),
        ):
            result = memory_cmd._cmd_memory(["filter", "on"])
        assert result == {"success": True}
        mf.assert_called_once_with(["on"])


# ── Fix 4: pipeline session passthrough ──


class TestPipelineSessionForwarding:
    def test_pipeline_forwards_session_to_steps(self, session):
        from l1.kernel.commands import get_registry

        captured: dict = {}
        registry = get_registry()
        registry.register_system(
            "pipe_probe",
            lambda args, session=None: captured.update(session=session) or {"success": True, "output": "ok"},
        )
        try:
            result = dispatch("/pipe_probe | /lang", session)
        finally:
            registry.unregister("pipe_probe")
        assert captured["session"] is session
        assert result.get("success") is True


# ── Fix 5: shlex guard ──


class TestDispatchParseGuard:
    def test_unbalanced_quote_returns_error_dict(self, session):
        result = dispatch('/echo "unclosed', session)
        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result


# ── Fix 6: prose with a pipe char ──


class TestProseWithPipe:
    def test_prose_pipe_falls_through_to_intent(self, session):
        """Natural language containing | reaches L3A, not the pipeline."""
        result = dispatch("compare alpha | beta", session)
        assert isinstance(result, dict)
        assert "pipeline" not in str(result.get("error", "")).lower()

    def test_real_pipeline_still_routes(self, session):
        result = dispatch("/help | /lang", session)
        assert isinstance(result, dict)


class TestLooksLikePipeline:
    def test_slash_head_is_pipeline(self):
        assert _looks_like_pipeline(["/help", "/lang"]) is True

    def test_registered_tool_head_is_pipeline(self):
        from l1.kernel.commands import get_registry

        registry = get_registry()
        registry.register_system("pipe_probe2", lambda args, session=None: {"success": True})
        try:
            assert _looks_like_pipeline(["pipe_probe2", "x"]) is True
        finally:
            registry.unregister("pipe_probe2")

    def test_prose_is_not_pipeline(self):
        assert _looks_like_pipeline(["compare", "alpha", "beta"]) is False

    def test_empty_head_is_not_pipeline(self):
        assert _looks_like_pipeline(["", "x"]) is False
