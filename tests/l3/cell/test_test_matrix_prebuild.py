"""Tests for l3.cell.test_matrix_prebuild — async parallel test-matrix prebuild."""

from __future__ import annotations


class TestTestMatrixPrebuild:
    """test-matrix prebuild — build, cache hit, degrade, switch off."""

    def test_build_matrix_bounded_rows(self):
        from l3.cell.test_matrix_prebuild import build_matrix

        rows = build_matrix("card-1", "run tests", "test")
        assert isinstance(rows, list)
        assert rows
        assert len(rows) <= 20  # TEST_MATRIX_PREBUILD_MAX
        assert rows[0]["case"] == "positive"
        assert rows[0]["card_id"] == "card-1"
        assert rows[0]["domain"] == "test"

    def test_prebuild_disabled_by_default(self, monkeypatch):
        from l3.cell.test_matrix_prebuild import prebuild_enabled

        assert prebuild_enabled() is False

    def test_prebuild_enabled_requires_switches_and_threshold(self, monkeypatch):
        from l1.kernel.settings import get_settings
        from l3.cell.test_matrix_prebuild import prebuild_enabled

        monkeypatch.setattr(
            get_settings(),
            "get",
            lambda key, default=False: key == "departments.test_matrix_prebuild",
        )
        # Switch on, but department division inactive (default) -> False.
        assert prebuild_enabled() is False

    def test_schedule_prebuild_noop_when_off(self):
        from l3.cell.test_matrix_prebuild import reset_test_matrix_prebuild, schedule_prebuild

        reset_test_matrix_prebuild()
        assert schedule_prebuild("cell-1", "card-1", "t", "test") is False

    def test_get_matrix_falls_back_to_sync_build(self, tmp_path, monkeypatch):
        # Cache miss / prebuild off -> synchronous rule-based matrix, never raises.
        from l3.cell.test_matrix_prebuild import get_matrix, reset_test_matrix_prebuild

        reset_test_matrix_prebuild()
        rows = get_matrix("cell-1", "card-1", intent="run tests", domain="test")
        assert isinstance(rows, list)
        assert rows
        assert rows[0]["case"] == "positive"

    def test_prebuild_one_caches_to_tiered_l2(self, monkeypatch):
        # Force the enabled path and drive the worker task directly; the
        # matrix must land in the tiered-cache L2 shared-summary surface.
        from l3.cell.test_matrix_prebuild import _matrix_key, _prebuild_one
        from l3.memory.tiered_cache import get_tiered_cache, reset_tiered_cache

        reset_tiered_cache()
        _prebuild_one("cell-1", "card-1", "run tests", "test")
        cached = get_tiered_cache().get_shared_summary("cell-1", _matrix_key("cell-1", "card-1"))
        assert isinstance(cached, list)
        assert cached
        assert cached[0]["card_id"] == "card-1"

    def test_get_matrix_returns_cached_when_present(self, monkeypatch):
        from l3.cell.test_matrix_prebuild import _matrix_key, get_matrix
        from l3.memory.tiered_cache import get_tiered_cache, reset_tiered_cache

        reset_tiered_cache()
        get_tiered_cache().set_shared_summary(
            "cell-1", _matrix_key("cell-1", "card-9"), [{"card_id": "card-9", "case": "custom", "entry": 0}]
        )
        rows = get_matrix("cell-1", "card-9", intent="ignored", domain="ignored")
        assert rows == [{"card_id": "card-9", "case": "custom", "entry": 0}]

    def test_tester_injection_skipped_for_non_tester(self):
        from l3.agent.agent_loop_context import AgentLoopContextMixin

        m = AgentLoopContextMixin.__new__(AgentLoopContextMixin)
        m._role = "writer"
        m._cell_id = "cell-1"
        m._last_card_id = "card-1"
        out = m._inject_test_matrix("base")
        assert out == "base"

    def test_tester_injection_degrades_when_off(self):
        from l3.agent.agent_loop_context import AgentLoopContextMixin

        m = AgentLoopContextMixin.__new__(AgentLoopContextMixin)
        m._role = "tester"
        m._cell_id = "cell-1"
        m._last_card_id = "card-1"
        m._card_domain = "test"
        m.task = "run tests"
        out = m._inject_test_matrix("base")
        # Prebuild switch off by default -> injection skipped (base unchanged).
        assert out == "base"
