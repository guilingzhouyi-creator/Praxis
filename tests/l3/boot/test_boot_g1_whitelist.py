"""Boot — G1 whitelist population (W2.3)."""

from __future__ import annotations


def test_register_g1_whitelist_populates_gatechain(monkeypatch) -> None:
    """_load_tools must hand every registry tool name to GateChain G1."""
    import l3.tool_system.tool_registry as tr
    from l1.kernel.gatechain import get_gatechain
    from l3.boot.boot_steps.tools import _load_tools

    monkeypatch.setattr(tr, "TOOL_REGISTRY", {"alpha": object(), "beta": object()})
    monkeypatch.setattr("l3.tool_system.tool_config.ToolConfig.load", lambda: 2)
    gc = get_gatechain()
    gc._known_tools = frozenset()  # simulate a fresh boot state

    result = _load_tools()
    assert result.get("success") is True
    assert "alpha" in gc._known_tools
    assert "beta" in gc._known_tools
