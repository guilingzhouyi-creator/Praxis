"""invoke_gated — single execution gate entry (W1.2)."""

from __future__ import annotations


def _prime(monkeypatch, tool_name: str = "read_file"):
    """Populate the tool registry and G1 whitelist for pipeline tests."""
    import l3.tool_system.tool_registry as tr
    from l3.tool_system.tool_spec import ToolSpec

    spec = ToolSpec(
        name=tool_name,
        description="test tool",
        category="test",
        ring="RING_1",
        danger=1,
        handler=lambda args, agent_id="": {"success": True, "data": "ok"},
    )
    monkeypatch.setattr(tr, "TOOL_REGISTRY", {tool_name: spec})
    from l1.kernel.gatechain import get_gatechain

    get_gatechain().register_tools([tool_name])
    # The registry-level executor reads the real tool registry, so patch it
    # to avoid depending on a full booted registry in unit tests.
    import l3.tool_system.tool_pipeline_steps as _tps

    def _fake_executor(name, args, agent_id=""):
        return {"success": True, "data": "ok"}

    monkeypatch.setattr(_tps, "_execute_tool_spec", _fake_executor)
    return spec


def test_invoke_gated_interactive_principal_executes(monkeypatch):
    """An unregistered interactive principal passes G2 but still runs the chain."""
    _prime(monkeypatch)
    from l3.tool_system.invoke import invoke_gated

    r = invoke_gated("read_file", {"path": "/tmp/x"}, agent_id="user:shell", interactive=True)
    assert r.get("success") is True, r
    steps = r.get("steps", [])
    assert any(s.get("phase") == "gatechain" for s in steps), "gatechain step missing"


def test_invoke_gated_unknown_tool_blocked(monkeypatch):
    """G1 still blocks tools outside the whitelist for interactive principals."""
    _prime(monkeypatch)
    from l3.tool_system.invoke import invoke_gated

    r = invoke_gated("nope", {}, agent_id="user:shell", interactive=True)
    assert r.get("success") is False


def test_invoke_gated_non_interactive_unregistered_blocked(monkeypatch):
    """A non-interactive unregistered agent is still blocked by G2."""
    _prime(monkeypatch)
    from l3.tool_system.invoke import invoke_gated

    r = invoke_gated("read_file", {"path": "/tmp/x"}, agent_id="ghost")
    assert r.get("success") is False
