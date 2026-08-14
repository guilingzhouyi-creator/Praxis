"""Tests for l1.kernel.identity_binding — per-Cell role binding registry."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Isolate the identity-binding persistence file per test.

    The registry now persists bindings (survives restarts); tests must not
    leak bindings across each other via the default data-dir state file.
    """
    monkeypatch.setenv("PRAXIS_IDENTITY_STATE", str(tmp_path / "id_bindings.json"))
    yield


class TestIdentityBindingManager:
    """identity binding — bind/get/unbind/resolve/write gate."""

    def test_bind_and_get(self):
        from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager

        reset_identity_binding_manager()
        mgr = get_identity_binding_manager()
        r = mgr.bind("cell-1", "writer", "You are the writer. Produce code only.", internal=True)
        assert r.get("success") is True
        b = mgr.get_binding("cell-1", "writer")
        assert b is not None
        assert b.prompt_fragment == "You are the writer. Produce code only."

    def test_write_gate_requires_identity(self):
        from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager

        reset_identity_binding_manager()
        mgr = get_identity_binding_manager()
        r = mgr.bind("cell-1", "writer", "fragment")
        assert r.get("success") is False
        assert "identity required" in r.get("error", "")

    def test_fragment_truncated_to_limit(self):
        from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager

        reset_identity_binding_manager()
        mgr = get_identity_binding_manager()
        r = mgr.bind("cell-1", "writer", "x" * 5000, max_chars=100, internal=True)
        assert r.get("success") is True
        assert r.get("chars") == 100
        assert len(mgr.get_binding("cell-1", "writer").prompt_fragment) == 100

    def test_resolve_default_fragment_when_unbound(self):
        from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager

        reset_identity_binding_manager()
        mgr = get_identity_binding_manager()
        frag = mgr.resolve_fragment("cell-1", "writer")
        assert "writer" in frag
        assert "cell-1" in frag

    def test_resolve_custom_fragment_takes_precedence(self):
        from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager

        reset_identity_binding_manager()
        mgr = get_identity_binding_manager()
        mgr.bind("cell-1", "writer", "STRICT WRITER ONLY", internal=True)
        assert mgr.resolve_fragment("cell-1", "writer") == "STRICT WRITER ONLY"

    def test_unbind_and_clear(self):
        from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager

        reset_identity_binding_manager()
        mgr = get_identity_binding_manager()
        mgr.bind("cell-1", "writer", "frag", internal=True)
        mgr.bind("cell-1", "reader", "frag", internal=True)
        r = mgr.unbind("cell-1", "writer", internal=True)
        assert r.get("success") is True
        assert mgr.get_binding("cell-1", "writer") is None
        assert mgr.cell_ids() == ["cell-1"]
        r = mgr.clear_cell("cell-1", internal=True)
        assert r.get("success") is True
        assert mgr.cell_ids() == []

    def test_bindings_for_cell_excludes_fragment(self):
        from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager

        reset_identity_binding_manager()
        mgr = get_identity_binding_manager()
        mgr.bind("cell-1", "writer", "secret fragment", internal=True)
        view = mgr.bindings_for_cell("cell-1")
        assert "writer" in view
        assert "prompt_fragment" not in view["writer"]
        assert view["writer"]["role"] == "writer"
