"""Tests for the memory-upgrade API handlers (corpus / digest / offload / sensitive / guard)."""

from __future__ import annotations

from l3.agent.agent_loop import reset_loop_registry
from l3.agent.compression_guard import reset_guard
from l3.agent.digest_cache import reset_digest
from l3.agent.sensitive_detect import reset_sensitive
from l3.agent.tool_result_cache import reset_tool_result
from l4.api_handlers.api_handlers_security import (
    memory_compression_guard_get,
    memory_compression_guard_set,
    memory_context_audit,
    memory_corpus_export,
    memory_digest_get,
    memory_digest_set,
    memory_prompt_library_get,
    memory_prompt_library_set,
    memory_sensitive_get,
    memory_sensitive_set,
    memory_tool_result_get,
    memory_tool_result_set,
)


def test_corpus_export_returns_count_and_samples():
    r = memory_corpus_export({"limit": 3})
    assert r["success"] is True
    assert "count" in r
    assert "samples" in r


def test_digest_get_and_set():
    reset_digest()
    try:
        st = memory_digest_get()
        assert "enabled" in st
        r = memory_digest_set({"enabled": True, "max_chars": 200})
        assert r["success"] is True
        assert memory_digest_get()["enabled"] is True
        assert memory_digest_get()["max_chars"] == 200
    finally:
        reset_digest()


def test_tool_result_get_and_set():
    reset_tool_result()
    try:
        st = memory_tool_result_get()
        assert "enabled" in st
        r = memory_tool_result_set({"enabled": True, "max_chars": 2000})
        assert r["success"] is True
        assert memory_tool_result_get()["enabled"] is True
    finally:
        reset_tool_result()


def test_sensitive_get_and_set():
    reset_sensitive()
    try:
        st = memory_sensitive_get()
        assert st["enabled"] is True  # default ON
        r = memory_sensitive_set({"enabled": False})
        assert r["success"] is True
        assert memory_sensitive_get()["enabled"] is False
    finally:
        reset_sensitive()


def test_compression_guard_get_and_set():
    reset_guard()
    try:
        st = memory_compression_guard_get()
        assert st["recursion_threshold"] == 0  # default off
        assert st["breaker_enabled"] is True  # default on
        r = memory_compression_guard_set({"recursion_threshold": 5, "breaker_enabled": False})
        assert r["success"] is True
        after = memory_compression_guard_get()
        assert after["recursion_threshold"] == 5
        assert after["breaker_enabled"] is False
    finally:
        reset_guard()


def test_context_audit_returns_aggregate():
    reset_loop_registry()
    try:
        r = memory_context_audit({"cell_id": "cell-9"})
        assert r["success"] is True
        assert "agents" in r
        assert "total_trail_messages" in r
        assert "per_agent" in r
    finally:
        reset_loop_registry()


def test_prompt_library_get_and_set():
    from l3.agent.global_prompt_library import reset_global_prompt_library
    from l3.agent.prompt_library import reset_prompt_library

    reset_prompt_library()
    reset_global_prompt_library()
    try:
        st = memory_prompt_library_get()
        assert st["cell"]["enabled"] is True  # default ON
        assert st["global"]["enabled"] is True
        r = memory_prompt_library_set({"cell": False, "global": False})
        assert r["success"] is True
        after = memory_prompt_library_get()
        assert after["cell"]["enabled"] is False
        assert after["global"]["enabled"] is False
    finally:
        reset_prompt_library()
        reset_global_prompt_library()
