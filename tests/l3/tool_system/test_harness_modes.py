"""Harness mode tests — governed / semi / minimal pipeline gate matrix.

Process steps (approval / rate / pool) may be skipped in lighter modes;
the safety bottom line (constitution, gatechain, sandbox, reference-channel
recording) is never skipped in any mode.
"""

from __future__ import annotations

from l1.kernel.params.tool import (
    HARNESS_MODE_CODE,
    HARNESS_MODE_DEFAULT,
    HARNESS_MODE_GOVERNED,
    HARNESS_MODE_MINIMAL,
    HARNESS_MODE_SEMI,
    HARNESS_MODE_STEPS,
    HARNESS_MODES,
)
from l3.tool_system.tool_pipeline import ToolPipeline
from l3.tool_system.tool_spec import ToolSpec


def _spec() -> ToolSpec:
    return ToolSpec(
        name="read_file", description="r", category="", ring="RING_1", danger=0, parameters=[], handler=None
    )


def _run(pipeline: ToolPipeline, mode: str, monkeypatch) -> dict:
    """Run execute() with a forced harness mode."""
    import l3.tool_system.harness as harness
    import l3.tool_system.tool_pipeline as tp

    calls: dict[str, int] = {}

    def _cfg(key: str, default=None):
        if key == "record_steps":
            return True
        if key == "exec_token_budget":
            return 1000
        return default

    monkeypatch.setattr(tp, "get_tool_config", _cfg)
    monkeypatch.setattr(harness, "get_harness_mode", lambda: mode)
    monkeypatch.setattr(tp, "agent_can_access", lambda *a, **k: True)

    class _Gate:
        def check(self, *a, **k):
            return {"allowed": True, "decision": "PASS", "steps": []}

    monkeypatch.setattr(tp, "_get_gatechain", lambda: _Gate())

    # stub the rate scheduler + policy so we can observe whether they ran
    class _Rate:
        def check(self, agent_id, ring):
            calls["rate"] = calls.get("rate", 0) + 1
            return {"allowed": True}

    # pipeline binds _rate_scheduler at construction — replace the instance attr
    pipeline._rate_scheduler = _Rate()

    def _requires_approval(agent_id, tool_name):
        calls["approval"] = calls.get("approval", 0) + 1
        return False  # no real approval request → no wait timeout

    monkeypatch.setattr(tp, "_ToolPolicy", type("P", (), {"requires_approval": staticmethod(_requires_approval)}))

    # minimal's toolset whitelist excludes read_file — use run_in_terminal
    # there so the process-step assertions still reach the gating chain.
    tool = "run_in_terminal" if mode == HARNESS_MODE_MINIMAL else "read_file"
    result = pipeline.execute(tool, "agent-http", _registry={}, _executor=lambda *a, **k: {"success": True})
    result["_calls"] = calls
    return result


class TestModeMatrix:
    def test_mode_constants(self):
        assert HARNESS_MODE_DEFAULT == HARNESS_MODE_GOVERNED
        assert set(HARNESS_MODES) == {
            HARNESS_MODE_GOVERNED,
            HARNESS_MODE_CODE,
            HARNESS_MODE_SEMI,
            HARNESS_MODE_MINIMAL,
        }
        assert HARNESS_MODE_STEPS[HARNESS_MODE_GOVERNED] == ()
        assert "approval" in HARNESS_MODE_STEPS[HARNESS_MODE_SEMI]
        assert {"approval", "rate", "pool"} <= set(HARNESS_MODE_STEPS[HARNESS_MODE_MINIMAL])

    def test_governed_runs_all_process_steps(self, monkeypatch):
        p = ToolPipeline()
        r = _run(p, HARNESS_MODE_GOVERNED, monkeypatch)
        assert r["harness_mode"] == HARNESS_MODE_GOVERNED
        assert r["_calls"].get("approval", 0) >= 1
        assert r["_calls"].get("rate", 0) >= 1

    def test_semi_skips_approval(self, monkeypatch):
        p = ToolPipeline()
        r = _run(p, HARNESS_MODE_SEMI, monkeypatch)
        assert r["harness_mode"] == HARNESS_MODE_SEMI
        assert r["_calls"].get("approval", 0) == 0
        assert r["_calls"].get("rate", 0) >= 1  # rate stays in semi

    def test_minimal_skips_approval_and_rate(self, monkeypatch):
        p = ToolPipeline()
        r = _run(p, HARNESS_MODE_MINIMAL, monkeypatch)
        assert r["harness_mode"] == HARNESS_MODE_MINIMAL
        assert r["_calls"].get("approval", 0) == 0
        assert r["_calls"].get("rate", 0) == 0

    def test_invalid_mode_falls_back(self, monkeypatch):
        p = ToolPipeline()
        r = _run(p, "weird-mode", monkeypatch)
        assert r["harness_mode"] == HARNESS_MODE_GOVERNED


class TestBottomLine:
    def test_constitution_never_skipped_in_minimal(self, monkeypatch):
        """Even minimal mode blocks constitution violations."""
        import l3.tool_system.harness as harness
        import l3.tool_system.tool_pipeline as tp

        p = ToolPipeline()
        monkeypatch.setattr(tp, "agent_can_access", lambda *a, **k: True)

        class _Gate:
            def check(self, *a, **k):
                return {"allowed": True, "decision": "PASS", "steps": []}

        monkeypatch.setattr(tp, "_get_gatechain", lambda: _Gate())
        monkeypatch.setattr(harness, "get_harness_mode", lambda: HARNESS_MODE_MINIMAL)

        # force minimal mode, constitution denies everything — bind the
        # instance attribute directly (bound at construction)
        class _Deny:
            def is_allowed(self, tool, agent, target="", territory=""):
                return {"allowed": False, "reason": "denied"}

        p.constitution = _Deny()
        monkeypatch.setattr(tp, "get_tool_config", lambda k, d=None: True if k == "record_steps" else d)
        _spec_obj = _spec()
        # minimal toolset whitelist excludes read_file — use run_in_terminal.
        r = p.execute("run_in_terminal", "agent-http", _registry={}, _executor=lambda *a, **k: {"success": True})
        assert not r["success"]
        from l2.i18n import t

        assert r["error"] == t("core.pipeline_constitution_blocked")

    def test_gatechain_recording_never_skipped(self, monkeypatch):
        """Reference-channel causal recording stays on in minimal mode."""
        import l3.tool_system.harness as harness
        import l3.tool_system.tool_pipeline as tp

        p = ToolPipeline()
        monkeypatch.setattr(tp, "agent_can_access", lambda *a, **k: True)

        class _Gate:
            def check(self, *a, **k):
                return {"allowed": True, "decision": "PASS", "steps": []}

        monkeypatch.setattr(tp, "_get_gatechain", lambda: _Gate())
        monkeypatch.setattr(harness, "get_harness_mode", lambda: HARNESS_MODE_MINIMAL)
        monkeypatch.setattr(tp, "get_tool_config", lambda k, d=None: True if k == "record_steps" else d)
        recorded = []

        class _RC:
            def tool_call(self, *a, **k):
                recorded.append(a[0])

        monkeypatch.setattr(tp, "_get_rc", lambda: _RC())
        r = p.execute("run_in_terminal", "agent-http", _registry={}, _executor=lambda *a, **k: {"success": True})
        assert r.get("harness_mode") == HARNESS_MODE_MINIMAL
        assert "run_in_terminal" in recorded


class TestControlBar:
    """Unified harness control bar — code level + minimal toolset + control line."""

    def test_control_line_keeps_approval_in_guarded_levels(self):
        from l1.kernel.params.tool import (
            HARNESS_CONTROL_LINE,
            HARNESS_MODE_CODE,
            HARNESS_MODE_GOVERNED,
            HARNESS_MODE_SEMI,
        )

        assert HARNESS_MODE_GOVERNED in HARNESS_CONTROL_LINE
        assert HARNESS_MODE_CODE in HARNESS_CONTROL_LINE
        assert HARNESS_MODE_SEMI not in HARNESS_CONTROL_LINE  # below the line

    def test_code_level_uses_full_control_steps(self):
        from l1.kernel.params.tool import HARNESS_MODE_CODE, HARNESS_MODE_STEPS

        assert HARNESS_MODE_STEPS[HARNESS_MODE_CODE] == ()

    def test_code_level_blocks_native_tools(self, monkeypatch):
        """code level: presentation=code → only run_code is callable."""
        import l3.tool_system.harness as harness
        import l3.tool_system.tool_pipeline as tp

        p = ToolPipeline()
        monkeypatch.setattr(tp, "get_tool_config", lambda k, d=None: True if k == "record_steps" else d)
        monkeypatch.setattr(harness, "get_harness_mode", lambda: "code")
        # default presentation is native unless synced; simulate sync via
        # harness.presentation wiring is covered elsewhere — here force code
        # presentation through the preset by patching get_presentation_mode.
        import l3.tool_system.tool_presentation as pres

        monkeypatch.setattr(pres, "get_presentation_mode", lambda: "code")
        r = p.execute("read_file", "agent-http", _registry={}, _executor=lambda *a, **k: {"success": True})
        assert not r["success"]
        assert "UNKNOWN_TOOL" in r["error"]

    def test_minimal_toolset_restricts_visible_tools(self, monkeypatch):
        """minimal level: toolset whitelist = bash + str_replace_editor."""
        import l3.tool_system.harness as harness
        import l3.tool_system.tool_pipeline as tp

        p = ToolPipeline()
        monkeypatch.setattr(tp, "get_tool_config", lambda k, d=None: True if k == "record_steps" else d)
        monkeypatch.setattr(harness, "get_harness_mode", lambda: "minimal")
        r = p.execute("read_file", "agent-http", _registry={}, _executor=lambda *a, **k: {"success": True})
        assert not r["success"]
        assert "UNKNOWN_TOOL" in r["error"]

    def test_minimal_allows_whitelisted_tool_through_filter(self, monkeypatch):
        """minimal level: run_in_terminal is whitelisted — passes the toolset
        filter (later gates may still block in this unit context)."""
        import l3.tool_system.harness as harness
        import l3.tool_system.tool_pipeline as tp

        p = ToolPipeline()
        monkeypatch.setattr(tp, "get_tool_config", lambda k, d=None: True if k == "record_steps" else d)
        monkeypatch.setattr(harness, "get_harness_mode", lambda: "minimal")
        r = p.execute("run_in_terminal", "agent-http", _registry={}, _executor=lambda *a, **k: {"success": True})
        # Toolset filter must NOT produce UNKNOWN_TOOL for a whitelisted tool.
        assert "UNKNOWN_TOOL" not in r.get("error", "")

    def test_set_harness_mode_syncs_presentation(self):
        """harness code level syncs presentation to code; others to native."""
        from l3.tool_system.harness import reset_harness_mode, set_harness_mode
        from l3.tool_system.tool_presentation import get_presentation_mode, reset_presentation_mode

        try:
            set_harness_mode("code", source="test")
            assert get_presentation_mode() == "code"
            set_harness_mode("governed", source="test")
            assert get_presentation_mode() == "native"
            set_harness_mode("minimal", source="test", confirmed=True)
            assert get_presentation_mode() == "native"
        finally:
            reset_harness_mode()
            reset_presentation_mode()
