"""Tests for the tool-result offload cache (B2)."""

from __future__ import annotations

from l3.agent.tool_result_cache import (
    fetch_result,
    maybe_offload,
    offload_result,
    reclaim,
    reset_tool_result,
    set_tool_result_switches,
    tool_result_status,
)


def test_enabled_by_default():
    reset_tool_result()
    try:
        assert tool_result_status()["enabled"] is True
        big = {"content": "x" * 5000}
        offloaded = maybe_offload("cell-A", "c1", "scan", big)
        assert offloaded["offloaded"] is True
        rec = fetch_result("cell-A", "c1")
        assert str(rec["result"]) == str(big)
    finally:
        reset_tool_result()


def test_oversized_result_offloaded_and_recoverable():
    reset_tool_result()
    try:
        set_tool_result_switches(enabled=True, max_chars=100)
        big = {"content": "x" * 500}
        r = maybe_offload("cell-A", "c2", "scan", big)
        assert r["offloaded"] is True
        assert r["tool"] == "scan"
        rec = fetch_result("cell-A", "c2")
        assert str(rec["result"]) == str(big)
    finally:
        reset_tool_result()


def test_small_result_not_offloaded():
    reset_tool_result()
    try:
        set_tool_result_switches(enabled=True, max_chars=100)
        small = {"content": "ok"}
        assert maybe_offload("cell-A", "c3", "read", small) == small
    finally:
        reset_tool_result()


def test_reclaim_clears_cell_offloaded_results():
    """reclaim drops this Cell's offloaded results (register + buffer)."""
    from l3.memory.tiered_cache import get_tiered_cache, reset_tiered_cache

    reset_tiered_cache()
    reset_tool_result()
    try:
        set_tool_result_switches(enabled=True)
        offload_result("cell-A", "c1", "scan", {"content": "big" * 100})
        offload_result("cell-A", "c2", "scan", {"content": "big" * 100})
        assert reclaim("cell-A") == 2
        assert get_tiered_cache().keys("L1") == []
    finally:
        reset_tool_result()
        reset_tiered_cache()


def test_reclaim_isolates_other_cell():
    """reclaim(cell-A) leaves cell-B's offloaded results untouched."""
    from l3.memory.tiered_cache import reset_tiered_cache

    reset_tiered_cache()
    reset_tool_result()
    try:
        set_tool_result_switches(enabled=True)
        offload_result("cell-A", "c1", "scan", {"content": "big" * 100})
        offload_result("cell-B", "c2", "read", {"content": "ok"})
        assert reclaim("cell-A") == 1
        assert fetch_result("cell-B", "c2").get("tool") == "read"
    finally:
        reset_tool_result()
        reset_tiered_cache()


def test_tool_result_read_registered_on_loop():
    """The AgentLoop registers tool_result_read when building run context."""
    from l3.agent.agent_loop import AgentLoop, reset_loop_registry
    from l3.agent.agent_loop_context import AgentLoopContextMixin

    loop = AgentLoop(task="t", agent_id="agent-x", cell_id="cell-A")
    try:
        AgentLoopContextMixin._register_tool_result_read(loop)
        names = [t.name for t in loop._tools]
        assert "tool_result_read" in names
        spec = next(t for t in loop._tools if t.name == "tool_result_read")
        assert spec.ring == "RING_1"
    finally:
        reset_loop_registry()


def test_tool_result_read_handler_roundtrip():
    """tool_result_read fetches an offloaded payload by call_id."""
    from l3.agent.agent_loop import AgentLoop, reset_loop_registry
    from l3.agent.agent_loop_context import AgentLoopContextMixin

    reset_tool_result()
    try:
        set_tool_result_switches(enabled=True, max_chars=10)
        loop = AgentLoop(task="t", agent_id="agent-y", cell_id="cell-A")
        AgentLoopContextMixin._register_tool_result_read(loop)
        spec = next(t for t in loop._tools if t.name == "tool_result_read")
        offload_result("cell-A", "c9", "scan", {"content": "full payload here"})
        out = spec.handler({"call_id": "c9"}, agent_id="agent-y")
        assert out["success"] is True
        assert out["result"]["content"] == "full payload here"
        assert out["tool"] == "scan"
        # Unknown call_id degrades gracefully.
        out2 = spec.handler({"call_id": "nope"}, agent_id="agent-y")
        assert out2["success"] is False
    finally:
        reset_tool_result()
        reset_loop_registry()


def test_tool_result_read_budget_capped():
    """Read-back respects TOOL_RESULT_READBACK_MAX_CHARS."""
    from l1.kernel.params.system import TOOL_RESULT_READBACK_MAX_CHARS
    from l3.agent.agent_loop import AgentLoop, reset_loop_registry
    from l3.agent.agent_loop_context import AgentLoopContextMixin

    reset_tool_result()
    try:
        set_tool_result_switches(enabled=True, max_chars=10)
        loop = AgentLoop(task="t", agent_id="agent-z", cell_id="cell-A")
        AgentLoopContextMixin._register_tool_result_read(loop)
        spec = next(t for t in loop._tools if t.name == "tool_result_read")
        offload_result("cell-A", "c10", "scan", {"content": "z" * (TOOL_RESULT_READBACK_MAX_CHARS * 2)})
        out = spec.handler({"call_id": "c10"}, agent_id="agent-z")
        assert out["success"] is True
        assert out["result"]["truncated"] is True
        assert "head" in out["result"] and "tail" in out["result"]
    finally:
        reset_tool_result()
        reset_loop_registry()
