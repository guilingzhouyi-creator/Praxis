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


def test_disabled_by_default():
    reset_tool_result()
    try:
        assert tool_result_status()["enabled"] is False
        big = {"content": "x" * 5000}
        assert maybe_offload("cell-A", "c1", "scan", big) == big
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
