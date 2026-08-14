"""Tests for L2 shell organization commands — identity-binding / departments / l3ac."""

from __future__ import annotations


class TestIdentityBindingCommand:
    """identity-binding — list/set/clear via L2 shell."""

    def test_set_requires_writer_role(self):
        from l2.l2_shell.commands import _cmd_identity_binding

        r = _cmd_identity_binding(["set", "cell-1", "writer", "Strict."])
        assert r.get("success") is False
        assert "--as" in r.get("error", "")

    def test_set_and_list_roundtrip(self):
        from l2.l2_shell.commands import _cmd_identity_binding

        r = _cmd_identity_binding(["set", "cell-1", "writer", "Strict writer.", "--as", "deployer"])
        assert r.get("success") is True
        lst = _cmd_identity_binding(["list", "cell-1"])
        assert lst.get("success") is True
        assert "writer" in lst.get("bindings", {})
        assert "prompt_fragment" not in lst["bindings"]["writer"]
        c = _cmd_identity_binding(["clear", "cell-1", "--as", "deployer"])
        assert c.get("success") is True

    def test_bad_max_option(self):
        from l2.l2_shell.commands import _cmd_identity_binding

        r = _cmd_identity_binding(["set", "cell-1", "writer", "frag", "--max", "abc", "--as", "deployer"])
        assert r.get("success") is False
        assert "--max" in r.get("error", "")

    def test_unknown_subcommand(self):
        from l2.l2_shell.commands import _cmd_identity_binding

        r = _cmd_identity_binding(["bogus"])
        assert r.get("success") is False


class TestDepartmentsCommand:
    """departments — status/route/enable/disable via L2 shell."""

    def test_enable_disable_switch(self):
        from l1.kernel.settings import get_settings
        from l2.l2_shell.commands import _cmd_departments

        try:
            r = _cmd_departments(["enable"])
            assert r.get("success") is True
            assert get_settings().get("departments.enabled") is True
        finally:
            # Restore the switch even on assertion failure so the persisted
            # settings cannot leak into later tests.
            _cmd_departments(["disable"])
        assert get_settings().get("departments.enabled") is False

    def test_route_with_cells(self):
        from l2.l2_shell.commands import _cmd_departments

        try:
            _cmd_departments(["enable"])
            route = _cmd_departments(["route", "test", "--cells", "3"])
            assert route.get("success") is True
            assert route["route"]["routed"] is True
            assert route["route"]["department"] == "test"
        finally:
            _cmd_departments(["disable"])

    def test_route_malformed_cells(self):
        from l2.l2_shell.commands import _cmd_departments

        r = _cmd_departments(["route", "test", "--cells"])
        assert r.get("success") is False
        assert "--cells" in r.get("error", "")
        r = _cmd_departments(["route", "test", "--cells", "abc"])
        assert r.get("success") is False
        assert "--cells" in r.get("error", "")

    def test_status_shape(self):
        from l2.l2_shell.commands import _cmd_departments

        r = _cmd_departments(["status"])
        assert r.get("success") is True
        assert "threshold" in r.get("departments", {})

    def test_unknown_subcommand(self):
        from l2.l2_shell.commands import _cmd_departments

        r = _cmd_departments(["bogus"])
        assert r.get("success") is False


class TestL3acCommand:
    """l3ac — status/contribute/reset via L2 shell."""

    def test_status_and_contribute(self):
        from l2.l2_shell.commands import _cmd_l3ac
        from l3.cell.peers.l3a.secretary import reset_secretary

        reset_secretary()
        try:
            st = _cmd_l3ac(["status"])
            assert st.get("success") is True
            assert st["secretary"]["mode"] == "assist"
            r = _cmd_l3ac(["contribute", "card", "true", "--card", "c1"])
            assert r.get("recorded") is True
            assert r.get("contribution_success") is True
        finally:
            reset_secretary()

    def test_contribute_rejects_invalid_boolean(self):
        from l2.l2_shell.commands import _cmd_l3ac
        from l3.cell.peers.l3a.secretary import reset_secretary

        reset_secretary()
        r = _cmd_l3ac(["contribute", "card", "ture"])
        assert r.get("success") is False
        assert "invalid boolean" in r.get("error", "")

    def test_contribute_requires_args(self):
        from l2.l2_shell.commands import _cmd_l3ac

        r = _cmd_l3ac(["contribute"])
        assert r.get("success") is False

    def test_unknown_subcommand(self):
        from l2.l2_shell.commands import _cmd_l3ac

        r = _cmd_l3ac(["bogus"])
        assert r.get("success") is False
