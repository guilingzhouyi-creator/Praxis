"""Tests for l3.cell.department — department division + directed transport."""

from __future__ import annotations


class TestDepartmentManager:
    """department division — threshold, switch, routing."""

    def test_inactive_by_default(self):
        from l3.cell.department import get_department_manager, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        assert m.enabled() is False
        assert m.active() is False

    def test_route_test_content_when_active(self, monkeypatch):
        from l3.cell.department import get_department_manager, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        monkeypatch.setattr(m, "enabled", lambda: True)
        monkeypatch.setattr(m, "cell_count", lambda: 3)
        assert m.active() is True
        r = m.route_content("test")
        assert r.get("routed") is True
        assert r.get("department") == "test"
        assert "tester" in r.get("roles", [])

    def test_no_routing_below_threshold(self, monkeypatch):
        from l3.cell.department import get_department_manager, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        monkeypatch.setattr(m, "enabled", lambda: True)
        monkeypatch.setattr(m, "cell_count", lambda: 1)
        assert m.active() is False
        r = m.route_content("test")
        assert r.get("routed") is False

    def test_department_for_role(self, monkeypatch):
        from l3.cell.department import get_department_manager, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        monkeypatch.setattr(m, "enabled", lambda: True)
        assert m.department_for_role("tester", cell_count=3) == "test"
        assert m.department_for_role("writer", cell_count=3) is None

    def test_status_reports_threshold(self, monkeypatch):
        from l3.cell.department import get_department_manager, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        monkeypatch.setattr(m, "enabled", lambda: True)
        monkeypatch.setattr(m, "cell_count", lambda: 2)
        s = m.status()
        assert s.get("active") is True
        assert s.get("threshold") == 2
        assert "test" in s.get("departments", [])

    def test_enable_switch_via_settings_api(self):
        """The departments.enabled switch is controllable through the
        settings surface that /api/v2/settings writes to."""
        from l1.kernel.settings import get_settings
        from l3.cell.department import get_department_manager, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        assert m.enabled() is False
        try:
            get_settings().set("departments.enabled", True)
            assert m.enabled() is True
        finally:
            get_settings().set("departments.enabled", False)


class TestDepartmentPhaseC:
    """Phase C — department definition, permission scope, executor override."""

    def test_loads_definition_scope_executor_from_yaml(self):
        from l3.cell.department import get_department_manager, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        dept = m._departments.get("test")
        assert dept is not None
        assert dept.definition != ""
        assert "test" in dept.permission_scope
        assert dept.executor != ""

    def test_route_refuses_outside_scope(self, monkeypatch):
        from l3.cell.department import get_department_manager, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        monkeypatch.setattr(m, "enabled", lambda: True)
        monkeypatch.setattr(m, "cell_count", lambda: 3)
        dept = m._departments["test"]
        # Anomalous scope that excludes the dept_type itself: the content type
        # matches the department (dept_type) but is outside its permission
        # scope -> refused (hard boundary, not just unmapped).
        dept.permission_scope = ["verification"]
        r = m.route_content("test")
        assert r.get("refused") is True
        assert r.get("routed") is False

    def test_route_allows_within_scope(self, monkeypatch):
        from l3.cell.department import get_department_manager, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        monkeypatch.setattr(m, "enabled", lambda: True)
        monkeypatch.setattr(m, "cell_count", lambda: 3)
        dept = m._departments["test"]
        dept.permission_scope = ["test", "verification", "matrix"]
        r = m.route_content("verification")
        assert r.get("routed") is True
        assert r.get("refused", False) is False

    def test_model_role_for_uses_executor_override(self):
        from l3.cell.department import get_department_manager, model_role_for, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        dept = m._departments["test"]
        dept.executor = "custom-executor"
        assert model_role_for("test") == "custom-executor"
        dept.executor = ""
        # Built-in fallback when no override.
        assert model_role_for("test") == "build"

    def test_disabled_department_not_indexed(self, monkeypatch):
        # P2#4 fix: a department with auto_enabled=false must not be resolved
        # by the role index fast path (consistent with the fallback scan that
        # skips disabled departments).
        from l3.cell.department import get_department_manager, reset_department_manager

        reset_department_manager()
        m = get_department_manager()
        monkeypatch.setattr(m, "enabled", lambda: True)
        monkeypatch.setattr(m, "cell_count", lambda: 3)
        m.register("dept-disabled", ["ghost-role"], "retired")
        m._departments["dept-disabled"].auto_enabled = False
        m._rebuild_indexes()
        assert m.department_for_role("ghost-role") is None
        assert "ghost-role" not in m._role_index
