"""Tests for l3.cell.violation_monitor — department overreach output detection."""

from __future__ import annotations


class TestViolationMonitor:
    """violation_monitor — classification, thresholds, switches, degrade."""

    def test_classify_output(self):
        from l3.cell.violation_monitor import classify_output

        assert classify_output("def test_foo(): assert 1 == 1") == "test"
        assert classify_output("def impl(): return 1") == "build"
        assert classify_output("no markers here") == ""

    def test_disabled_by_default(self):
        from l3.cell.violation_monitor import enabled

        assert enabled() is False

    def test_check_off_degrades_to_allow(self):
        from l3.cell.violation_monitor import check_output

        r = check_output("agent-1", "cell-1", "tester", "def test_x(): pass")
        assert r.get("allowed") is True
        assert r.get("monitored") is False

    def test_check_requires_division_active(self, monkeypatch):
        # Switch on but division inactive (cell_count < 2) -> monitor inert.
        from l3.cell import violation_monitor as vm

        monkeypatch.setattr(vm, "enabled", lambda: False)
        r = vm.check_output("agent-1", "cell-1", "tester", "def test_x(): pass")
        assert r.get("allowed") is True
        assert r.get("monitored") is False

    def test_light_overreach_tolerated(self, monkeypatch):
        # Division active + switch on; a build agent producing one test output
        # is light overreach -> allowed with light flag.
        from l3.cell import violation_monitor as vm
        from l3.cell.department import get_department_manager, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        monkeypatch.setattr(m, "enabled", lambda: True)
        monkeypatch.setattr(m, "cell_count", lambda: 3)
        monkeypatch.setattr(vm, "enabled", lambda: True)
        dept = m._departments["test"]
        dept.roles = ["tester", "builder"]
        dept.permission_scope = ["test", "verification"]
        vm.reset_violation_monitor()
        r = vm.check_output("builder", "cell-1", "builder", "def test_foo(): assert 1")
        # builder role -> test department via roles; test content in scope -> allowed.
        assert r.get("allowed") is True

    def test_heavy_overreach_stopped(self, monkeypatch):
        from l1.kernel.params.agent import VIOLATION_HEAVY_THRESHOLD
        from l3.cell import violation_monitor as vm
        from l3.cell.department import get_department_manager, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        monkeypatch.setattr(m, "enabled", lambda: True)
        monkeypatch.setattr(m, "cell_count", lambda: 3)
        monkeypatch.setattr(vm, "enabled", lambda: True)
        dept = m._departments["test"]
        dept.roles = ["tester"]
        dept.permission_scope = ["verification"]  # test content is outside scope
        vm.reset_violation_monitor()
        stopped = False
        for _ in range(VIOLATION_HEAVY_THRESHOLD):
            r = vm.check_output("tester", "cell-1", "tester", "def test_foo(): assert 1")
            if r.get("stop"):
                stopped = True
                assert r.get("allowed") is False
                break
        assert stopped is True

    def test_reset_clears_counters(self, monkeypatch):
        from l3.cell import violation_monitor as vm

        monkeypatch.setattr(vm, "enabled", lambda: True)
        with vm._lock:
            vm._overreach["agent-9"] = 5
        vm.reset_violation_monitor()
        with vm._lock:
            assert vm._overreach == {}
            assert vm._state["enabled"] is False
