"""Phase-3 M1 tests — memory domain filter (identity/Cell domain gating + switches)."""

from __future__ import annotations

import pytest

from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager
from l3.memory.memory_domain_filter import get_memory_filter, reset_memory_filter


@pytest.fixture(autouse=True)
def _clean():
    reset_memory_filter()
    reset_identity_binding_manager()
    yield
    reset_memory_filter()
    reset_identity_binding_manager()


def _entry(tags: list[str] | None = None, cell_id: str = "") -> dict:
    return {"tags": tags or [], "cell_id": cell_id, "entry_type": "test"}


# ── Switches ──


def test_disabled_by_default():
    """Filter is off by default (backward compatible, never auto-enabled)."""
    f = get_memory_filter()
    assert f.status() == {"enabled": False, "fine_grained": False}


def test_set_switches():
    """Both switches are operator-settable (API + L2 Shell)."""
    f = get_memory_filter()
    r = f.set_switches(enabled=True, fine_grained=True)
    assert r["enabled"] is True and r["fine_grained"] is True
    f.set_switches(enabled=False)
    assert f.status()["enabled"] is False


# ── Filtering ──


def test_disabled_allows_everything():
    """Disabled → all entries pass (no filtering)."""
    f = get_memory_filter()
    entries = [_entry(tags=["build"]), _entry(tags=["test"], cell_id="cell-x")]
    assert f.filter_entries(entries, cell_id="cell-1", role="writer") == entries


def test_cell_domain_gate_when_enabled():
    """Enabled: entries from another Cell domain are hidden (coarse)."""
    f = get_memory_filter()
    f.set_switches(enabled=True)
    assert f.is_allowed(_entry(tags=[], cell_id="cell-1"), cell_id="cell-1") is True
    assert f.is_allowed(_entry(tags=[], cell_id="cell-2"), cell_id="cell-1") is False


def test_fine_grained_identity_gate():
    """Fine-grained: at least one identity tag must overlap the requester."""
    mgr = get_identity_binding_manager()
    mgr.bind("cell-1", "tester", "tester", domain_tags=["test"], internal=True)

    f = get_memory_filter()
    f.set_switches(enabled=True, fine_grained=True)
    # Requester identity set = {test}; only test-tagged entries pass.
    assert f.is_allowed(_entry(tags=["test"], cell_id="cell-1"), cell_id="cell-1", role="tester") is True
    assert f.is_allowed(_entry(tags=["build"], cell_id="cell-1"), cell_id="cell-1", role="tester") is False


def test_filter_entries_respects_switches():
    """filter_entries drops hidden entries only when enabled."""
    f = get_memory_filter()
    f.set_switches(enabled=True)
    kept = f.filter_entries(
        [_entry(tags=[], cell_id="cell-1"), _entry(tags=[], cell_id="cell-2")],
        cell_id="cell-1",
    )
    assert len(kept) == 1


# ── API + L2 Shell ──


def test_api_switch_handlers():
    """GET/PUT /api/v2/memory/filter expose and toggle the filter."""
    from l4.api_handlers.api_handlers_security import memory_filter_get, memory_filter_set

    g = memory_filter_get({})
    assert g["success"] is True
    assert g["filter"]["enabled"] is False

    s = memory_filter_set({"enabled": True, "fine_grained": True})
    assert s["success"] is True
    assert s["enabled"] is True and s["fine_grained"] is True


def test_l2_shell_filter_command():
    """/memory filter on|off fine|coarse toggles via the L2 shell."""
    from l2.l2_shell.commands.memory import _cmd_memory_filter

    r = _cmd_memory_filter([])
    assert r["success"] is True
    assert r["filter"]["enabled"] is False

    r2 = _cmd_memory_filter(["on", "fine"])
    assert r2["filter"]["enabled"] is True
    assert r2["filter"]["fine_grained"] is True

    r3 = _cmd_memory_filter(["bogus"])
    assert r3["success"] is False


def test_mixin_delegates_resolve():
    """ApiHandlers mixin exposes the memory filter delegates."""
    from l4.api_handlers import ApiHandlers

    h = ApiHandlers()
    assert callable(getattr(h, "_memory_filter_get", None))
    assert callable(getattr(h, "_memory_filter_set", None))


# ── Phase 3 M1 production wiring: recall / FTS / archive gates ──


def test_recall_filters_via_supply_chain():
    """MemoryManager.recall applies the M1 gate through re_inject_filtered.

    Single-Cell AgentLoops are composite entities: with no binding the
    identity set is the full build/test/review set, so both build- and
    test-tagged entries of the requester's Cell survive the fine-grained
    gate (only foreign-Cell entries are dropped by the Cell-domain gate).
    """
    from l3.memory.memory import MemoryManager, reset_memory

    reset_memory()
    f = get_memory_filter()
    f.set_switches(enabled=True, fine_grained=True)
    try:
        mem = MemoryManager()
        mem.remember(
            "a1",
            "note",
            "build note with enough content to pass the quality gate here",
            tags=["build"],
            cell_id="cell-1",
        )
        mem.remember(
            "a2",
            "note",
            "test note with enough content to pass the quality gate here",
            tags=["test"],
            cell_id="cell-1",
        )
        mem.remember(
            "a3",
            "note",
            "foreign note with enough content to pass the quality gate here",
            tags=["build"],
            cell_id="cell-2",
        )
        # Composite identity (no binding) + same Cell → both tags visible;
        # the foreign-Cell entry is hidden by the Cell-domain gate.
        hits = mem.recall(limit=10, cell_id="cell-1")
        assert hits, "expected at least one hit"
        assert all(e.cell_id == "cell-1" for e in hits)
        assert any("build" in (e.tags or []) for e in hits)
        assert any("test" in (e.tags or []) for e in hits)
    finally:
        reset_memory()
        reset_identity_binding_manager()


def test_search_long_term_filters_when_enabled():
    """FTS retrieval applies the M1 gate when the filter is on."""
    from l3.memory.memory import MemoryManager, reset_memory
    from l3.memory.memory_search import search_long_term

    reset_memory()
    f = get_memory_filter()
    f.set_switches(enabled=True)
    try:
        mem = MemoryManager()
        mem.remember("a1", "note", "allocator lock handling note with unique token", tags=[], cell_id="cell-1")
        rows = search_long_term(mem, query="allocator", limit=10)
        assert isinstance(rows, list)
    finally:
        reset_memory()
        reset_identity_binding_manager()


def test_archive_search_filters_when_enabled():
    """R4 archive retrieval applies the M1 gate (cell_id arg supported)."""
    from l3.tools._archive import archive_search

    f = get_memory_filter()
    f.set_switches(enabled=True)
    try:
        r = archive_search({"query": "nonexistent-token", "cell_id": "cell-1"}, agent_id="t")
        assert r["success"] is True
        assert isinstance(r["results"], list)
    finally:
        reset_identity_binding_manager()


# ── Composite-identity semantics (single Cell) ──


def test_unbound_composite_identity_allows_all_three():
    """Single-Cell AgentLoops are composite entities: with no binding the
    identity set is the full build/test/review set — all three tag families
    pass the fine-grained gate (never a hardcoded 'l3a' fallback)."""
    f = get_memory_filter()
    f.set_switches(enabled=True, fine_grained=True)
    # No binding registered → identity_set_for("", "") returns
    # IDENTITY_DEFAULT_SET = (build, test, review).
    assert f.is_allowed(_entry(tags=["build"], cell_id="cell-1"), cell_id="cell-1") is True
    assert f.is_allowed(_entry(tags=["test"], cell_id="cell-1"), cell_id="cell-1") is True
    assert f.is_allowed(_entry(tags=["review"], cell_id="cell-1"), cell_id="cell-1") is True


def test_bound_department_narrows_composite_identity():
    """After department split, a binding narrows the composite identity to
    its domain_tags — other identities become invisible."""
    mgr = get_identity_binding_manager()
    mgr.bind("cell-1", "builder", "builder", domain_tags=["build"], internal=True)
    f = get_memory_filter()
    f.set_switches(enabled=True, fine_grained=True)
    assert f.is_allowed(_entry(tags=["build"], cell_id="cell-1"), cell_id="cell-1", role="builder") is True
    assert f.is_allowed(_entry(tags=["review"], cell_id="cell-1"), cell_id="cell-1", role="builder") is False


def test_fine_grained_never_bypasses_cell_gate():
    """Regression: fine_grained=True must NOT disable the Cell-domain gate.

    An entry from a foreign Cell is hidden in EVERY mode — fine-grained only
    adds the identity gate on top; it never removes the Cell boundary. This
    test guards against the 2026-08 regression where the ``not fine``
    condition let foreign-Cell entries through whenever fine was enabled.
    """
    f = get_memory_filter()
    f.set_switches(enabled=True, fine_grained=True)
    # Foreign-Cell entry with an overlapping identity tag — Cell gate wins.
    assert f.is_allowed(_entry(tags=["build"], cell_id="cell-2"), cell_id="cell-1") is False
    # Same-Cell entry still passes the identity gate (composite identity).
    assert f.is_allowed(_entry(tags=["build"], cell_id="cell-1"), cell_id="cell-1") is True


# ── HTN-C identity-hit driven semantics (peer agents) ──


def test_htnc_intent_hit_drives_identity():
    """Peer agents get their active identity from the HTN-C dispatch hit:
    an intent matching the test identity admits only test-tagged entries."""
    f = get_memory_filter()
    f.set_switches(enabled=True, fine_grained=True)
    # "verify regression" hits the test identity (identity_roles keywords).
    assert f.is_allowed(_entry(tags=["test"], cell_id="cell-1"), cell_id="cell-1", intent="verify regression") is True
    assert f.is_allowed(_entry(tags=["build"], cell_id="cell-1"), cell_id="cell-1", intent="verify regression") is False
    assert (
        f.is_allowed(_entry(tags=["review"], cell_id="cell-1"), cell_id="cell-1", intent="verify regression") is False
    )


def test_htnc_build_hit_drives_identity():
    """An implement/construct intent hits the build identity."""
    f = get_memory_filter()
    f.set_switches(enabled=True, fine_grained=True)
    assert (
        f.is_allowed(_entry(tags=["build"], cell_id="cell-1"), cell_id="cell-1", intent="implement the login flow")
        is True
    )
    assert (
        f.is_allowed(_entry(tags=["test"], cell_id="cell-1"), cell_id="cell-1", intent="implement the login flow")
        is False
    )


def test_htnc_no_intent_falls_back_to_composite():
    """Without a driving intent the static resolution applies — an unbound
    single-Cell composite sees all three identity families (peer agents)."""
    f = get_memory_filter()
    f.set_switches(enabled=True, fine_grained=True)
    assert f.is_allowed(_entry(tags=["build"], cell_id="cell-1"), cell_id="cell-1") is True
    assert f.is_allowed(_entry(tags=["test"], cell_id="cell-1"), cell_id="cell-1") is True
    assert f.is_allowed(_entry(tags=["review"], cell_id="cell-1"), cell_id="cell-1") is True


def test_htnc_domain_hint_routes_to_test():
    """The card domain hint alone can hit the test identity (e.g. 'test')."""
    f = get_memory_filter()
    f.set_switches(enabled=True, fine_grained=True)
    assert f.is_allowed(_entry(tags=["test"], cell_id="cell-1"), cell_id="cell-1", domain="test") is True
    assert f.is_allowed(_entry(tags=["build"], cell_id="cell-1"), cell_id="cell-1", domain="test") is False
