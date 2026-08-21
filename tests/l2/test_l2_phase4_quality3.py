"""Phase 4 batch 3 — remaining handler contracts (skills writes, memory ops, model list).

Same discipline as batch 2: mocked L1/L3 boundaries, dict-shape
assertions only — no object assertions that would couple tests to L3
internals the TS side never sees.
"""

from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture
def sm():
    with mock.patch("l1.kernel.skill.get_skill_manager") as g:
        mgr = mock.MagicMock()
        mgr.authorize_write.return_value = (True, "dev")
        mgr.list_skills.return_value = [{"name": "s1"}]
        g.return_value = mgr
        yield mgr


def _skills(args):
    from l2.l2_shell.commands.system import _cmd_skills

    return _cmd_skills(args)


class TestSkillsWriteParsers:
    def test_register_usage_error(self, sm):
        assert _skills(["register"])["success"] is False

    def test_register_parses_flags_and_persists(self, sm):
        with mock.patch("l2.bridge.r4_register_custom_skill", return_value={"success": True, "persisted": True}) as reg:
            r = _skills(
                [
                    "register",
                    "n",
                    "d",
                    "prompt text",
                    "--scope",
                    "agent",
                    "--identity",
                    "a9",
                    "--priority",
                    "3",
                    "--tags",
                    "x,y",
                    "--tools",
                    "rf,wf",
                ]
            )
        reg.assert_called_once()
        kwargs = reg.call_args.kwargs
        assert kwargs["tags"] == ["x", "y"] and kwargs["priority"] == 3
        assert r["persisted"] is True and r["authorized"] == "dev"

    def test_register_requires_prompt(self, sm):
        r = _skills(["register", "n", "d", "--scope", "global"])
        assert r["success"] is False and "prompt" in r["error"]

    def test_register_falls_back_to_memory_create(self, sm):
        sm.create.return_value = {"success": True}
        with mock.patch("l2.bridge.r4_register_custom_skill", side_effect=RuntimeError("no l3")):
            with mock.patch("l2.bridge.link_skill_graph", return_value={"linked": 0}):
                r = _skills(["register", "n", "d", "p"])
        sm.create.assert_called_once()
        assert r["linked"] == 0

    def test_evolve_gates_then_forwards(self, sm):
        with mock.patch("l2.bridge.r4_evolve_skill", return_value={"success": True}) as ev:
            r = _skills(["evolve", "make", "tea"])
        ev.assert_called_once_with("make tea")
        assert r["success"] is True
        sm.authorize_write.assert_called()

    def test_evolve_requires_intent(self, sm):
        assert _skills(["evolve"])["success"] is False

    def test_update_speed_flag_validation(self, sm):
        assert _skills(["update-speed", "fast", "bogus"])["success"] is False
        sm.set_update_policy.reset_mock()
        _skills(["update-speed", "fast", "on"])
        sm.set_update_policy.assert_called_once_with(update_speed="fast", enabled=True, source="shell")

    def test_distill_set_field_validation(self, sm):
        bad = _skills(["distill", "set", "ghost-field", "on"])
        assert bad["success"] is False
        _skills(["distill", "set", "distill", "off"])
        sm.set_distill_policy.assert_called_once_with(distill=False, source="shell")

    def test_pipeline_set_numeric_fields(self, sm):
        _skills(["pipeline", "set", "contrib_min_trials", "9"])
        sm.set_pipeline_policy.assert_called_once_with(contrib_min_trials=9, source="shell")
        sm.set_pipeline_policy.reset_mock()
        _skills(["pipeline", "set", "retrieval_min_score", "0.5"])
        sm.set_pipeline_policy.assert_called_once_with(retrieval_min_score=0.5, source="shell")

    def test_pipeline_set_rejects_garbage(self, sm):
        r = _skills(["pipeline", "set", "contrib_min_trials", "abc"])
        assert r["success"] is False

    def test_disclosure_set_toggle_and_limit(self, sm):
        _skills(["disclosure", "set", "full_index_enabled", "off"])
        sm.set_disclosure_policy.assert_called_once_with(full_index_enabled=False, source="shell")
        sm.set_disclosure_policy.reset_mock()
        _skills(["disclosure", "set", "full_index_limit", "42"])
        sm.set_disclosure_policy.assert_called_once_with(full_index_limit=42, source="shell")


class TestSystemSmallCommands:
    def test_status_returns_output_block_and_mode(self):
        from l2.l2_shell.commands.system import _cmd_status

        r = _cmd_status([])
        assert isinstance(r.get("output"), str) and r["output"]
        assert r.get("mode") in ("L3A", "DIRECT")

    def test_intents_scheduler_observe_passthrough(self):
        from l2.l2_shell.commands.system import _cmd_intents, _cmd_observe, _cmd_scheduler

        with mock.patch("l2.bridge.think_registry_stats", return_value={"n": 1}):
            assert _cmd_intents([]) == {"success": True, "intents": {"n": 1}}
        with mock.patch("l2.bridge.scheduler_stats", return_value={"q": 0}):
            assert _cmd_scheduler([])["data"] == {"q": 0}
        with mock.patch("l2.bridge.obs_bus_summary", return_value={"events": 0}):
            assert _cmd_observe([])["data"] == {"events": 0}

    def test_cache_uses_default_cell_bridge(self):
        from l2.l2_shell.commands.system import _cmd_cache

        with mock.patch("l2.bridge.cell_cache_stats", return_value={"hits": 3}) as cc:
            r = _cmd_cache([])
        cc.assert_called_once()
        assert r["cache"] == {"hits": 3}

    def test_sysinfo_shape(self):
        from l2.l2_shell.commands.system import _cmd_sysinfo

        r = _cmd_sysinfo([])
        assert r["success"] is True and "python" in r and "platform" in r


class TestMemoryRemainingOps:
    def test_compaction_mode(self):
        from l2.l2_shell.commands.memory import _cmd_memory

        with mock.patch("l2.bridge.compaction_status", return_value={"mode": "deterministic"}):
            assert _cmd_memory(["compaction"])["mode"] == "deterministic"
        with mock.patch("l2.bridge.set_compaction_mode", return_value={"set": 1}) as sc:
            assert _cmd_memory(["compaction", "llm-assisted"]) == {"set": 1}
        sc.assert_called_once_with("llm-assisted")

    def test_premise_guard_and_inject_dedup(self):
        from l2.l2_shell.commands.memory import _cmd_memory

        with mock.patch("l2.bridge.premise_guard_status", return_value={}):
            _cmd_memory(["premise-guard"])
        with mock.patch("l2.bridge.set_premise_guard", return_value={"ok": 1}) as sp:
            assert _cmd_memory(["premise-guard", "off"]) == {"ok": 1}
        sp.assert_called_once_with(enabled=False)
        with mock.patch("l2.bridge.inject_dedup_status", return_value={}):
            _cmd_memory(["inject-dedup"])
        with mock.patch("l2.bridge.set_inject_dedup", return_value={"ok": 2}) as si:
            assert _cmd_memory(["inject-dedup", "on"]) == {"ok": 2}
        si.assert_called_once_with(enabled=True)

    def test_prompt_monitor_stats_and_emit(self):
        from l2.l2_shell.commands.memory import _cmd_memory

        with (
            mock.patch("l2.bridge.prompt_monitor_status", return_value={"enabled": True}),
            mock.patch("l2.bridge.prompt_monitor_stats", return_value={"hits": 4}),
        ):
            r = _cmd_memory(["prompt-monitor", "stats"])
        assert r["hits"] == 4
        with mock.patch("l2.bridge.emit_prompt_metrics", return_value={"emitted": 1}):
            assert _cmd_memory(["prompt-monitor", "emit"]) == {"emitted": 1}

    def test_prompt_library_global_kwarg(self):
        from l2.l2_shell.commands.memory import _cmd_memory

        with (
            mock.patch("l2.bridge.prompt_library_status", return_value={}),
            mock.patch("l2.bridge.global_prompt_library_status", return_value={}),
            mock.patch("l2.bridge.set_prompt_library_switches", return_value={}) as sp,
            mock.patch("l2.bridge.set_global_prompt_library_switches", return_value={}) as sg,
        ):
            _cmd_memory(["prompt-library", "on", "global=off"])
        sp.assert_called_once_with(enabled=True)
        sg.assert_called_once_with(enabled=False)

    def test_context_audit_forwards_cell(self):
        from l2.l2_shell.commands.memory import _cmd_memory

        with mock.patch("l2.bridge.audit_cell_context", return_value={"cells": 1}) as ac:
            _cmd_memory(["context-audit", "cell-7"])
        ac.assert_called_once_with(cell_id="cell-7")

    def test_corpus_limit(self):
        from l2.l2_shell.commands.memory import _cmd_memory

        with mock.patch("l2.bridge.export_corpus", return_value={"rows": []}) as ec:
            _cmd_memory(["corpus", "15"])
        ec.assert_called_once_with(limit=15)

    def test_agent_search_scope_shape(self):
        """``agent <id> search <query>`` resolves the id then recalls."""
        from l2.l2_shell.commands.memory import _cmd_memory

        mem = mock.MagicMock()
        mem.recall.return_value = {"items": []}
        with (
            mock.patch("l2.bridge.terminals", lambda: {"a1": object()}),
            mock.patch("l2.bridge.memory", lambda: mem),
        ):
            r = _cmd_memory(["agent", "a1", "search", "hello"])
        assert r["agent"] == "a1"
        mem.recall.assert_called_once()


class TestModelListPaths:
    def test_model_list_formats_roles(self):
        from l2.l2_shell.commands.model import _cmd_model

        with mock.patch("l2.bridge.model_resolve", return_value={"provider": "ollama", "model": "m1"}):
            r = _cmd_model(["list"])
        assert r["success"] is True and "Providers" in r["output"]

    def test_model_set_writes_prefixed_keys(self):
        from l2.l2_shell.commands.model import _cmd_model

        with mock.patch("l2.bridge.settings_set") as ss:
            r = _cmd_model(["set", "coder", "provider", "deepseek"])
        ss.assert_called_once()
        key = ss.call_args.args[0]
        assert key.startswith("model.coder.")
        assert r["success"] is True

    def test_model_status_note(self):
        from l2.l2_shell.commands.model import _cmd_model

        assert _cmd_model(["status"])["note"]


class TestTerminalRenderBranches:
    @pytest.fixture
    def shell(self):
        from l2.shells.terminal import TerminalShell

        return TerminalShell()

    def test_render_help_and_tools(self, shell, capsys):
        shell._render({"type": "help", "commands": [{"name": "/lang", "help": "h"}], "more": 2})
        out = capsys.readouterr().out
        assert "/lang" in out and "2" in out
        shell._render({"type": "tools", "tools": [{"name": "rf", "description": "read"}], "total": 1})
        assert "rf" in capsys.readouterr().out

    def test_render_intent_success_and_failure(self, shell, capsys):
        shell._render({"type": "intent", "success": True, "card_id": "c1"})
        assert "c1" in capsys.readouterr().out
        shell._render({"type": "intent", "success": False, "error": "bad"})
        assert "bad" in capsys.readouterr().out

    def test_render_tool_data_truncates_to_limit(self, shell, capsys):
        data = {f"k{i}": "v" for i in range(20)}
        shell._render({"type": "tool", "success": True, "data": data})
        out = capsys.readouterr().out
        assert "k0:" in out

    def test_render_generic_dict_fallback(self, shell, capsys):
        shell._render({"type": "mystery", "alpha": 1})
        assert "alpha" in capsys.readouterr().out
