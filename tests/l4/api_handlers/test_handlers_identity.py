"""Tests for l4.api_handlers.api_handlers_identity — binding CRUD."""

from __future__ import annotations


class TestIdentityBindingHandlers:
    """identity binding API — put/get/delete + validation + write gate."""

    def test_put_get_delete_roundtrip(self):
        from l4.api_handlers.api_handlers_identity import (
            handle_identity_binding_delete,
            handle_identity_binding_get,
            handle_identity_binding_put,
        )

        r = handle_identity_binding_put(
            {
                "cell_id": "cell-1",
                "role": "writer",
                "fragment": "Strict writer.",
                "domain_tags": ["codegen"],
                "writer_role": "deployer",
            }
        )
        assert r.get("success") is True
        g = handle_identity_binding_get({"cell_id": "cell-1"})
        assert g.get("success") is True
        assert "writer" in g.get("bindings", {})
        assert "prompt_fragment" not in g["bindings"]["writer"]
        assert g["bindings"]["writer"]["domain_tags"] == ["codegen"]
        d = handle_identity_binding_delete({"cell_id": "cell-1", "role": "writer", "writer_role": "deployer"})
        assert d.get("success") is True
        g2 = handle_identity_binding_get({"cell_id": "cell-1"})
        assert "writer" not in g2.get("bindings", {})

    def test_get_all_cells(self):
        from l4.api_handlers.api_handlers_identity import (
            handle_identity_binding_get,
            handle_identity_binding_put,
        )

        handle_identity_binding_put(
            {"cell_id": "cell-a", "role": "reader", "fragment": "Read only.", "writer_role": "deployer"}
        )
        g = handle_identity_binding_get({})
        assert g.get("success") is True
        assert "cell-a" in g.get("cells", {})

    def test_put_requires_fields(self):
        from l4.api_handlers.api_handlers_identity import handle_identity_binding_put

        r = handle_identity_binding_put({"cell_id": "cell-1"})
        assert r.get("success") is False
        r = handle_identity_binding_put({"cell_id": "cell-1", "role": "writer"})
        assert r.get("success") is False

    def test_put_requires_writer_role(self):
        """No privileged default — a caller without an explicit accepted
        writer role must be denied by the write gate."""
        from l4.api_handlers.api_handlers_identity import handle_identity_binding_put

        r = handle_identity_binding_put({"cell_id": "cell-1", "role": "writer", "fragment": "frag", "writer_role": ""})
        assert r.get("success") is False
        assert "writer_role" in r.get("error", "")

    def test_put_rejects_non_privileged_writer(self):
        from l4.api_handlers.api_handlers_identity import handle_identity_binding_put

        r = handle_identity_binding_put(
            {"cell_id": "cell-1", "role": "writer", "fragment": "frag", "writer_role": "reader"}
        )
        assert r.get("success") is False
        assert "may not mutate" in r.get("error", "")

    def test_put_rejects_bad_max_chars(self):
        from l4.api_handlers.api_handlers_identity import handle_identity_binding_put

        r = handle_identity_binding_put(
            {
                "cell_id": "cell-1",
                "role": "writer",
                "fragment": "frag",
                "writer_role": "deployer",
                "max_chars": "abc",
            }
        )
        assert r.get("success") is False
        assert "max_chars" in r.get("error", "")
        # Negative values must be rejected, not silently slice the fragment.
        r = handle_identity_binding_put(
            {
                "cell_id": "cell-1",
                "role": "writer",
                "fragment": "frag",
                "writer_role": "deployer",
                "max_chars": -5,
            }
        )
        assert r.get("success") is False

    def test_put_clamps_oversized_max_chars(self):
        """Caller-supplied limits never exceed the registry cap."""
        from l1.kernel.identity_binding import get_identity_binding_manager
        from l1.kernel.params.agent import IDENTITY_BINDING_MAX_CHARS
        from l4.api_handlers.api_handlers_identity import (
            handle_identity_binding_get,
            handle_identity_binding_put,
        )

        r = handle_identity_binding_put(
            {
                "cell_id": "cell-1",
                "role": "writer",
                "fragment": "x" * 5000,
                "writer_role": "deployer",
                "max_chars": 999999,
            }
        )
        assert r.get("success") is True
        b = get_identity_binding_manager().get_binding("cell-1", "writer")
        assert len(b.prompt_fragment) <= IDENTITY_BINDING_MAX_CHARS
        g = handle_identity_binding_get({"cell_id": "cell-1"})
        assert g["bindings"]["writer"]["max_chars"] <= IDENTITY_BINDING_MAX_CHARS

    def test_delete_requires_fields(self):
        from l4.api_handlers.api_handlers_identity import handle_identity_binding_delete

        r = handle_identity_binding_delete({"cell_id": "cell-1"})
        assert r.get("success") is False

    def test_definition_put_coerces_non_string(self):
        # P3#5 fix: a non-string definition body must be coerced to str
        # instead of crashing bind()'s slicing with a server error.
        from l4.api_handlers.api_handlers_identity import (
            handle_identity_binding_put,
            handle_identity_definition_put,
        )

        # Bind first (with a deployer writer).
        b = handle_identity_binding_put(
            {
                "cell_id": "cell-1",
                "role": "writer",
                "fragment": "frag",
                "writer_role": "deployer",
            }
        )
        assert b.get("success") is True
        # Int definition -> coerced to "123", no crash, success.
        r = handle_identity_definition_put(
            {
                "cell_id": "cell-1",
                "role": "writer",
                "definition": 123,
                "writer_role": "deployer",
            }
        )
        assert r.get("success") is True
        # List definition -> coerced, no crash.
        r2 = handle_identity_definition_put(
            {
                "cell_id": "cell-1",
                "role": "writer",
                "definition": ["a", "b"],
                "writer_role": "deployer",
            }
        )
        assert r2.get("success") is True
