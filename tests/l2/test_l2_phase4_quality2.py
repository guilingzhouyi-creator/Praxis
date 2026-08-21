"""Phase 4 batch 2 — skills/memory/model handler contracts over mocked L1/L3.

The SkillManager is an L1 port; every /skills subcommand must degrade to
a dict without importing L3 directly (candidates go through the
``r4_candidates`` port). These pins keep that boundary honest while
covering the dispatch table the TS engine mirrors entry-for-entry.
"""

from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture
def sm():
    """A MagicMock SkillManager with authorize_write defaulting to allow."""
    with mock.patch("l1.kernel.skill.get_skill_manager") as g:
        mgr = mock.MagicMock()
        mgr.authorize_write.return_value = (True, "dev")
        mgr.list_skills.return_value = [{"name": "s1"}]
        mgr.get.return_value = {"name": "s1"}
        g.return_value = mgr
        yield mgr


def _skills(args, session=None):
    from l2.l2_shell.commands.system import _cmd_skills

    return _cmd_skills(args, session=session)


class TestSkillsReadPaths:
    def test_list_truncates_and_counts(self, sm):
        r = _skills(["list"])
        assert r["success"] is True and r["count"] == 1

    def test_lean_filters_by_tag(self, sm):
        r = _skills(["lean"])
        assert r["success"] is True
        sm.list_skills.assert_called_once_with(tags=["lean_case"])

    def test_get_returns_skill_or_error(self, sm):
        assert _skills(["get", "s1"])["skill"]["name"] == "s1"
        sm.get.return_value = None
        assert _skills(["get", "ghost"])["success"] is False

    def test_permissions_reports_policy(self, sm):
        sm.write_policy.return_value = {"ring": 3}
        assert _skills(["permissions"])["policy"] == {"ring": 3}

    def test_distill_status_public(self, sm):
        sm.distill_policy.return_value = {"distill": True}
        assert _skills(["distill"])["policy"] == {"distill": True}

    def test_retriever_status_and_set(self, sm):
        with (
            mock.patch("l2.bridge.retriever_status", return_value={"backend": "tfidf"}) as rs,
            mock.patch("l2.bridge.set_retriever_backend", return_value={"ok": 1}) as sb,
        ):
            assert _skills(["retriever"])["backend"] == "tfidf"
            rs.assert_called_once()
            r = _skills(["retriever", "set", "embedding"])
            sb.assert_called_once_with(backend="embedding")
            assert r == {"ok": 1}


class TestSkillsWritePaths:
    def test_create_requires_args_and_forwards(self, sm):
        assert _skills(["create"])["success"] is False
        _skills(["create", "n", "d", "p", "--role", "reviewer"])
        sm.create.assert_called_once()

    def test_update_validates_field(self, sm):
        assert _skills(["update", "n", "ghost-field", "v"])["success"] is False
        _skills(["update", "n", "prompt", "new-prompt"])
        sm.update.assert_called_once()

    def test_delete_delegates_gate_to_skill_manager(self, sm):
        """create/update/delete pass caller identity through; L1 gates."""
        r = _skills(["delete", "s1", "--role", "guest"])
        sm.delete.assert_called_once_with("s1", agent_id="", role="guest")
        assert r is sm.delete.return_value

    def test_reload_loads_builtin(self, sm):
        sm.load_builtin.return_value = 7
        assert _skills(["reload"])["loaded"] == 7

    def test_enable_disable_flip_status(self, sm):
        sm.update.return_value = {"success": True}
        assert _skills(["enable", "s1"])["enabled"] is True
        assert _skills(["disable", "s1"])["enabled"] is False

    def test_guidance_set_forwards_mode(self, sm):
        sm.set_guidance_policy.return_value = {"mode": "small"}
        assert _skills(["guidance", "set", "small"]) == {"mode": "small"}

    def test_pipeline_status_public(self, sm):
        sm.pipeline_policy.return_value = {"retrieval": True}
        assert _skills(["pipeline"])["policy"] == {"retrieval": True}

    def test_disclosure_status_public(self, sm):
        sm.disclosure_policy.return_value = {"full_index_enabled": True}
        assert _skills(["disclosure"])["policy"] == {"full_index_enabled": True}


class TestSkillsCandidates:
    def test_candidates_via_r4_port(self, sm):
        store = mock.MagicMock()
        store.list_candidates.return_value = [{"id": "c1"}]
        store.status.return_value = {"enabled": True}
        with mock.patch("l1.kernel.ports.get_port", return_value=store):
            r = _skills(["candidates", "list"])
        assert r["count"] == 1 and r["policy"] == {"enabled": True}

    def test_candidates_missing_port_degrades(self, sm):
        with mock.patch("l1.kernel.ports.get_port", side_effect=KeyError("r4_candidates")):
            assert _skills(["candidates"])["success"] is False

    def test_candidate_transition_gates_write(self, sm):
        store = mock.MagicMock()
        store.validate.return_value = {"validated": True}
        sm.authorize_write.return_value = (True, "dev")
        with mock.patch("l1.kernel.ports.get_port", return_value=store):
            r = _skills(["candidate", "validate", "c9"])
        store.validate.assert_called_once_with("c9")
        assert r == {"validated": True}


# ── /memory global op parsing (commands/memory.py) ──


class TestMemoryGlobalOps:
    def test_digest_toggle_and_max_chars(self):
        from l2.l2_shell.commands.memory import _cmd_memory

        with (
            mock.patch("l2.bridge.set_digest_switches", return_value={"on": 1}) as sd,
            mock.patch("l2.bridge.digest_status", return_value={}),
        ):
            assert _cmd_memory(["digest", "on"]) == {"on": 1}
            sd.assert_called_once_with(enabled=True)
            _cmd_memory(["digest", "max_chars=99"])
            sd.assert_called_with(max_chars=99)

    def test_tool_result_toggle(self):
        from l2.l2_shell.commands.memory import _cmd_memory

        with mock.patch("l2.bridge.set_tool_result_switches", return_value={"off": 1}) as st:
            assert _cmd_memory(["tool-result", "off"]) == {"off": 1}
        st.assert_called_once_with(enabled=False)

    def test_sensitive_action_parsing(self):
        from l2.l2_shell.commands.memory import _cmd_memory

        with mock.patch("l2.bridge.sensitive_status", return_value={"enabled": True}):
            assert _cmd_memory(["sensitive"]) == {"enabled": True}
        with mock.patch("l2.bridge.set_sensitive_switches", return_value={"set": 1}) as ss:
            _cmd_memory(["sensitive", "action=redact"])
        ss.assert_called_once_with(enabled=None, action="redact")

    def test_compression_guard_threshold_and_breaker(self):
        from l2.l2_shell.commands.memory import _cmd_memory

        with mock.patch("l2.bridge.guard_status", return_value={}):
            _cmd_memory(["compression-guard"])
        with mock.patch("l2.bridge.set_guard_switches", return_value={"set": 1}) as sg:
            _cmd_memory(["compression-guard", "threshold=42", "breaker=off"])
        sg.assert_called_once_with(recursion_threshold=42, breaker_enabled=False)

    def test_card_dispatch_branches(self):
        from l2.l2_shell.commands.memory import _cmd_card

        cr = mock.MagicMock()
        cr.list.return_value = [{"id": "k1"}]
        cr.submit.return_value = {"success": True}
        cr.cancel.return_value = True
        with mock.patch("l2.bridge.card_registry", lambda: cr):
            assert _cmd_card([])["data"]["cards"] == [{"id": "k1"}]
            _cmd_card(["list"])
            cr.list.assert_called_with(state=None)
            _cmd_card(["submit", "do things"])
            cr.submit.assert_called_once()
            _cmd_card(["cancel", "k1"])
            cr.cancel.assert_called_once()


# ── /l3a daemon bootstrap guard ──


class TestL3ABootstrap:
    def test_l3a_starts_daemon_once(self):
        import l2.l2_shell.commands.l3a as l3a_mod

        l3a_mod._l3a_initialized = False
        with (
            mock.patch("l2.bridge.l3a_start") as start,
            mock.patch.object(l3a_mod, "_l3a_dispatch", return_value={"success": True}) as disp,
        ):
            l3a_mod._cmd_l3a(["status"])
            l3a_mod._cmd_l3a(["status"])
        start.assert_called_once()
        assert disp.call_count == 2
        l3a_mod._l3a_initialized = False
