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
