"""Tests for the tool-result offload cache (B2)."""

from __future__ import annotations

from l3.agent.tool_result_cache import (
    fetch_result,
    maybe_offload,
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
