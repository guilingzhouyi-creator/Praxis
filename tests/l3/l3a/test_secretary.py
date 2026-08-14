"""Tests for l3.cell.peers.l3a.secretary — L3A-C capability upgrade."""

from __future__ import annotations


class TestL3ACSecretary:
    """secretary — assist→peer capability-threshold upgrade."""

    def test_starts_in_assist_mode(self):
        from l3.cell.peers.l3a.secretary import get_secretary, reset_secretary

        reset_secretary()
        s = get_secretary()
        assert s.mode() == "assist"
        assert s.commission_spec() == "secretary"

    def test_upgrades_to_peer_at_threshold(self):
        from l3.cell.peers.l3a.secretary import L3ACSecretary

        s = L3ACSecretary(threshold=2)
        r = s.contribute("analysis", success=True, card_id="c1")
        assert r["mode"] == "assist"
        assert r["upgraded"] is False
        r = s.contribute("card", success=True, card_id="c2")
        assert r["mode"] == "peer"
        assert r["upgraded"] is True
        assert s.commission_spec() == "secretary-peer"

    def test_failure_retreats_score(self):
        from l3.cell.peers.l3a.secretary import L3ACSecretary

        s = L3ACSecretary(threshold=2)
        s.contribute("analysis", success=True)
        s.contribute("report", success=False)
        assert s.score() == 0
        assert s.mode() == "assist"
        assert s.commission_spec() == "secretary"

    def test_score_bounded_at_zero(self):
        from l3.cell.peers.l3a.secretary import L3ACSecretary

        s = L3ACSecretary(threshold=2)
        s.contribute("analysis", success=False)
        assert s.score() == 0

    def test_specs_registered_in_pool(self):
        from l3.cell.peers.l3a import subagent

        assert "secretary" in subagent._L3A_SPECS
        assert "secretary-peer" in subagent._L3A_SPECS

    def test_status_shape(self):
        from l3.cell.peers.l3a.secretary import L3ACSecretary

        s = L3ACSecretary(threshold=3)
        st = s.status()
        assert st["mode"] == "assist"
        assert st["threshold"] == 3
        assert st["contributions"] == 0

    def test_history_bounded(self):
        from l3.cell.peers.l3a import params as _p
        from l3.cell.peers.l3a.secretary import L3ACSecretary

        s = L3ACSecretary(threshold=10**9)
        for i in range(_p.L3AC_HISTORY_MAX + 5):
            s.contribute("analysis", success=True, card_id=f"c{i}")
        assert s.status()["contributions"] == _p.L3AC_HISTORY_MAX

    def test_contribute_reports_actual_outcome(self):
        from l3.cell.peers.l3a.secretary import L3ACSecretary

        s = L3ACSecretary(threshold=5)
        r = s.contribute("card", success=False, card_id="c1")
        assert r["recorded"] is True
        assert r["contribution_success"] is False
        assert s.score() == 0

    def test_enable_switch_via_settings_api(self):
        """l3a.secretary.enabled is controllable through the settings
        surface that /api/v2/settings writes to."""
        from l1.kernel.settings import get_settings
        from l3.cell.peers.l3a.secretary import L3ACSecretary

        s = L3ACSecretary()
        assert s.enabled() is True
        try:
            get_settings().set("l3a.secretary.enabled", False)
            assert s.enabled() is False
        finally:
            get_settings().set("l3a.secretary.enabled", True)

    def test_spawn_routes_secretary_through_commission_spec(self, monkeypatch):
        """The spawn handler commissions the secretary with the mode spec."""
        from l3.cell.peers.l3a import subagent

        captured = {}

        class _FakePool:
            def commission(self, spec="", task="", group="", expect=None):
                captured["spec"] = spec
                return {"success": True, "spec": spec}

        class _FakeSec:
            def enabled(self):
                return True

            def commission_spec(self):
                return "secretary-peer"

        monkeypatch.setattr(subagent, "get_pool", lambda: _FakePool())
        monkeypatch.setattr("l3.cell.peers.l3a.secretary.get_secretary", lambda: _FakeSec())
        subagent.l3a_spawn_handler({"spec": "secretary", "task": "t"})
        assert captured["spec"] == "secretary-peer"

    def test_spawn_keeps_other_specs(self, monkeypatch):
        """Non-secretary specs are commissioned unchanged."""
        from l3.cell.peers.l3a import subagent

        captured = {}

        class _FakePool:
            def commission(self, spec="", task="", group="", expect=None):
                captured["spec"] = spec
                return {"success": True}

        monkeypatch.setattr(subagent, "get_pool", lambda: _FakePool())
        subagent.l3a_spawn_handler({"spec": "investigator", "task": "t"})
        assert captured["spec"] == "investigator"
