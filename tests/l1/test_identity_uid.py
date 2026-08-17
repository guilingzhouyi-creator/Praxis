"""Tests for l1.kernel.identity_uid — system-issued identity UID issuer."""

from __future__ import annotations


class TestIdentityUid:
    """identity_uid — issuance, uniqueness, verification, reset."""

    def test_issue_returns_prefixed_uid(self):
        from l1.kernel.identity_uid import issue_identity_uid, verify_identity_uid

        uid = issue_identity_uid()
        assert uid.startswith("id-")
        assert verify_identity_uid(uid) is True

    def test_issue_unique_across_calls(self):
        from l1.kernel.identity_uid import issue_identity_uid

        uids = {issue_identity_uid() for _ in range(50)}
        assert len(uids) == 50  # no duplicates

    def test_verify_rejects_malformed(self):
        from l1.kernel.identity_uid import verify_identity_uid

        assert verify_identity_uid("") is False
        assert verify_identity_uid("id-") is False
        assert verify_identity_uid("plain-1234567890abcdef") is False  # wrong prefix
        assert verify_identity_uid("id-123") is False  # wrong body length

    def test_reset_clears_seen_set(self):
        from l1.kernel import identity_uid as uid_mod

        uid_mod.reset_identity_uid()
        first = uid_mod.issue_identity_uid()
        uid_mod.reset_identity_uid()
        second = uid_mod.issue_identity_uid()
        assert first != second  # after reset the same body may be re-issued

    def test_track_existing_prevents_reissue(self):
        from l1.kernel import identity_uid as uid_mod

        uid_mod.reset_identity_uid()
        uid = uid_mod.issue_identity_uid()
        uid_mod._track_existing(uid)
        # Issuing again must not produce the tracked uid (seen-set holds it).
        for _ in range(200):
            assert uid_mod.issue_identity_uid() != uid


class TestIdentityBindingUid:
    """identity_binding — bindings carry a system-issued identity_id."""

    def test_bind_issues_identity_id(self):
        from l1.kernel.identity_binding import (
            get_identity_binding_manager,
            reset_identity_binding_manager,
        )

        reset_identity_binding_manager()
        m = get_identity_binding_manager()
        r = m.bind("cell-1", "writer", "frag", domain_tags=["codegen"], internal=True)
        assert r.get("success") is True
        uid = r.get("identity_id", "")
        assert uid.startswith("id-")
        assert m.get_binding("cell-1", "writer").identity_id == uid

    def test_to_dict_exposes_identity_id(self):
        from l1.kernel.identity_binding import (
            get_identity_binding_manager,
            reset_identity_binding_manager,
        )

        reset_identity_binding_manager()
        m = get_identity_binding_manager()
        m.bind("cell-1", "writer", "frag", internal=True)
        d = m.bindings_for_cell("cell-1")["writer"]
        assert d.get("identity_id", "").startswith("id-")

    def test_rebind_keeps_identity_id(self):
        from l1.kernel.identity_binding import (
            get_identity_binding_manager,
            reset_identity_binding_manager,
        )

        reset_identity_binding_manager()
        m = get_identity_binding_manager()
        r1 = m.bind("cell-1", "writer", "frag-a", internal=True)
        uid1 = r1["identity_id"]
        r2 = m.bind("cell-1", "writer", "frag-b", internal=True)
        assert r2["identity_id"] == uid1  # rebind keeps the UID stable


class TestIdentityDefinition:
    """identity definition (Phase B) — default, custom, cap, resolve."""

    def test_bind_resolves_builtin_definition(self):
        from l1.kernel.identity_binding import (
            get_identity_binding_manager,
            reset_identity_binding_manager,
        )

        reset_identity_binding_manager()
        m = get_identity_binding_manager()
        m.bind("cell-1", "build", "frag", internal=True)
        b = m.get_binding("cell-1", "build")
        # Built-in generalized definition from the prompt registry.
        assert "Build identity" in b.definition

    def test_custom_definition_wins(self):
        from l1.kernel.identity_binding import (
            get_identity_binding_manager,
            reset_identity_binding_manager,
        )

        reset_identity_binding_manager()
        m = get_identity_binding_manager()
        m.bind("cell-1", "build", "frag", internal=True, definition="Custom build definition")
        assert m.resolve_definition("cell-1", "build") == "Custom build definition"

    def test_definition_capped_at_max_chars(self):
        from l1.kernel.identity_binding import (
            get_identity_binding_manager,
            reset_identity_binding_manager,
        )
        from l1.kernel.params.agent import IDENTITY_DEFINITION_MAX_CHARS

        reset_identity_binding_manager()
        m = get_identity_binding_manager()
        m.bind("cell-1", "build", "frag", internal=True, definition="x" * 1000)
        assert len(m.resolve_definition("cell-1", "build")) <= IDENTITY_DEFINITION_MAX_CHARS

    def test_to_dict_excludes_definition(self):
        from l1.kernel.identity_binding import (
            get_identity_binding_manager,
            reset_identity_binding_manager,
        )

        reset_identity_binding_manager()
        m = get_identity_binding_manager()
        m.bind("cell-1", "build", "frag", internal=True, definition="secret-definition")
        d = m.bindings_for_cell("cell-1")["build"]
        assert "definition" not in d  # definition excluded from external views

    def test_resolve_definition_unbound_returns_builtin(self):
        from l1.kernel.identity_binding import (
            get_identity_binding_manager,
            reset_identity_binding_manager,
        )

        reset_identity_binding_manager()
        m = get_identity_binding_manager()
        # No binding: falls back to the built-in generalized definition.
        assert m.resolve_definition("cell-x", "test") != ""
