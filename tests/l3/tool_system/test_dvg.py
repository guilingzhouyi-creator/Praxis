"""DVG — declarative tool dependency graph tests."""

from __future__ import annotations

import pytest

from l3.tool_system.dvg import get_dvg, reset_dvg


@pytest.fixture(autouse=True)
def _reset_dvg():
    """Fresh graph per test (no singleton pollution)."""
    reset_dvg()
    yield
    reset_dvg()


def test_register_and_query_deps():
    """Deps_of / dependents_of round-trip."""
    dvg = get_dvg()
    assert dvg.register_tool_deps("tool_a", ["tool_b", "tool_c"])
    assert dvg.register_tool_deps("tool_b", [])
    assert dvg.register_tool_deps("tool_c", [])
    assert dvg.deps_of("tool_a") == ["tool_b", "tool_c"]
    assert dvg.dependents_of("tool_b") == ["tool_a"]
    assert dvg.all_names() == ["tool_a", "tool_b", "tool_c"]


def test_cycle_rejected():
    """A→B→A must be rejected, leaving the graph consistent."""
    dvg = get_dvg()
    assert dvg.register_tool_deps("tool_a", ["tool_b"])
    assert not dvg.register_tool_deps("tool_b", ["tool_a"])  # cycle
    assert dvg.deps_of("tool_b") == []
    assert dvg.cycles() == []


def test_can_run_missing_prereq():
    """can_run is False when a prerequisite is unregistered."""
    dvg = get_dvg()
    dvg.register_tool_deps("tool_a", ["ghost_tool"])
    assert not dvg.can_run("tool_a")
    dvg.register_tool_deps("ghost_tool", [])
    assert dvg.can_run("tool_a")


def test_topo_order_prereqs_first():
    """Topological order lists prerequisites before dependents."""
    dvg = get_dvg()
    dvg.register_tool_deps("app", ["db", "cache"])
    dvg.register_tool_deps("db", ["base"])
    dvg.register_tool_deps("cache", [])
    dvg.register_tool_deps("base", [])
    order = dvg.topo_order()
    assert order.index("base") < order.index("db") < order.index("app")
    assert order.index("cache") < order.index("app")


def test_unregister_removes_edges():
    """Unregistering a node also strips incoming edges."""
    dvg = get_dvg()
    dvg.register_tool_deps("tool_a", ["tool_b"])
    dvg.register_tool_deps("tool_b", [])
    assert dvg.unregister("tool_b")
    assert dvg.deps_of("tool_a") == []
    assert dvg.can_run("tool_a")  # no prereqs left


def test_to_dict_snapshot():
    """Serializable view reflects the graph."""
    dvg = get_dvg()
    dvg.register_tool_deps("tool_a", ["tool_b"])
    dvg.register_tool_deps("tool_b", [])
    assert dvg.to_dict() == {"tool_a": ["tool_b"], "tool_b": []}
