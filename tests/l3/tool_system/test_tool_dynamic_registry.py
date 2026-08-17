"""Dynamic tool registration tests — ToolConfig.register_from_dict + API handlers."""

from __future__ import annotations

import pytest

from l3.tool_system.tool_config import ToolConfig
from l3.tool_system.tool_registry import get_registry


@pytest.fixture(autouse=True)
def _reset_registry():
    """Ensure a clean registry per test (no singleton pollution)."""
    reg = get_registry()
    names = list(reg.all_names())
    yield
    for n in names:
        reg.unregister(n)
    for n in list(reg.all_names()):
        if getattr(reg.get(n), "category", "") == "dynamic":
            reg.unregister(n)


def test_register_from_dict_ok():
    """A valid spec registers and is queryable."""
    r = ToolConfig.register_from_dict(
        "probe_test_tool",
        {
            "description": "Probe a target for banner metadata",
            "handler": "l3.tools._comm.ask_user",  # existing resolvable handler
            "danger": 2,
        },
        ring="ring_2_5",
    )
    assert r.get("success") is True, r
    spec = get_registry().get("probe_test_tool")
    assert spec is not None
    assert spec.ring == "ring_2_5"
    assert spec.danger == 2


def test_register_from_dict_rejects_bad_ring():
    """Rings outside the whitelist are rejected."""
    r = ToolConfig.register_from_dict(
        "bad_ring_tool", {"description": "x", "handler": "l3.tools._comm.ask_user"}, ring="ring_9"
    )
    assert r.get("success") is False
    assert "not allowed" in r.get("error", "")


def test_register_from_dict_rejects_duplicate():
    """Registering the same name twice fails the second time."""
    spec = {"description": "x", "handler": "l3.tools._comm.ask_user"}
    assert ToolConfig.register_from_dict("dup_tool", spec)["success"] is True
    r = ToolConfig.register_from_dict("dup_tool", spec)
    assert r.get("success") is False
    assert "already registered" in r.get("error", "")


def test_register_from_dict_rejects_missing_handler():
    """A spec whose handler cannot be resolved is rejected eagerly."""
    r = ToolConfig.register_from_dict("ghost_tool", {"description": "x", "handler": "no.such.module.nope"})
    assert r.get("success") is False
    assert "handler not found" in r.get("error", "")


def test_dynamic_registration_wires_dvg_and_g1_then_cleans_up():
    """Dynamic tool lifecycle updates the DVG and G1 whitelist symmetrically."""
    from l1.kernel.gatechain import get_gatechain
    from l3.tool_system.dvg import get_dvg, reset_dvg
    from l3.tool_system.tool_registry import reset_registry

    reset_registry()
    reset_dvg()
    try:
        base = ToolConfig.register_from_dict("dynamic-base", {"handler": "l3.tools._comm.ask_user"})
        assert base["success"] is True
        composite = ToolConfig.register_from_dict(
            "dynamic-composite",
            {"handler": "l3.tools._comm.ask_user", "depends_on": ["dynamic-base"]},
        )
        assert composite["success"] is True
        assert get_dvg().execution_plan("dynamic-composite") == ["dynamic-base", "dynamic-composite"]
        assert {"dynamic-base", "dynamic-composite"} <= set(get_gatechain()._known_tools)

        assert get_registry().unregister("dynamic-composite") is True
        assert "dynamic-composite" not in get_dvg().all_names()
        assert "dynamic-composite" not in get_gatechain()._known_tools
        assert get_registry().unregister("dynamic-base") is True
        assert "dynamic-base" not in get_gatechain()._known_tools
    finally:
        reset_registry()
        reset_dvg()


def test_dynamic_registration_rejects_handler_outside_reviewed_namespace():
    """Dynamic config cannot import arbitrary application handlers."""
    result = ToolConfig.register_from_dict("outside-tool", {"handler": "os.system"})
    assert result["success"] is False
    assert "outside allowed" in result["error"]


def test_dynamic_registration_rejects_dependency_cycle_atomically():
    """A cyclic dynamic dependency cannot leave a registry-only tool behind."""
    from l3.tool_system.dvg import get_dvg, reset_dvg

    reset_dvg()
    try:
        first = ToolConfig.register_from_dict(
            "cycle-a", {"handler": "l3.tools._comm.ask_user", "depends_on": ["cycle-b"]}
        )
        assert first["success"] is True
        second = ToolConfig.register_from_dict(
            "cycle-b", {"handler": "l3.tools._comm.ask_user", "depends_on": ["cycle-a"]}
        )
        assert second["success"] is False
        assert get_registry().get("cycle-b") is None
        assert get_dvg().cycles() == []
    finally:
        reset_dvg()


def test_api_handlers_roundtrip():
    """POST /api/v2/tools/register + unregister roundtrip via the handlers."""
    from l4.api_handlers.api_handlers_tools import tool_register, tool_unregister

    r = tool_register({"name": "api_tool_test", "spec": {"description": "x", "handler": "l3.tools._comm.ask_user"}})
    assert r.get("success") is True, r
    assert get_registry().get("api_tool_test") is not None
    u = tool_unregister({"name": "api_tool_test"})
    assert u.get("success") is True
    assert get_registry().get("api_tool_test") is None


def test_api_handler_requires_name_and_spec():
    """Missing payload fields return a structured error."""
    from l4.api_handlers.api_handlers_tools import tool_register

    r = tool_register({"name": "", "spec": {}})
    assert r.get("success") is False
    assert "required" in r.get("error", "")
