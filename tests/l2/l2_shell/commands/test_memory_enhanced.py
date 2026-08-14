"""Tests for the L2 memory command extensions (corpus / digest / offload / sensitive / guard)."""

from __future__ import annotations

from l2.l2_shell.commands.memory import _cmd_memory
from l3.agent.agent_loop import reset_loop_registry
from l3.agent.compression_guard import reset_guard
from l3.agent.digest_cache import reset_digest
from l3.agent.sensitive_detect import reset_sensitive
from l3.agent.tool_result_cache import reset_tool_result


def test_corpus_op_global_no_agents_needed():
    r = _cmd_memory(["corpus", "2"])
    assert r["success"] is True
    assert "count" in r


def test_digest_op_switch():
    reset_digest()
    try:
        r = _cmd_memory(["digest", "on"])
        assert r["success"] is True
        assert r["enabled"] is True
        r2 = _cmd_memory(["digest"])
        assert r2["enabled"] is True
        _cmd_memory(["digest", "off"])
        assert _cmd_memory(["digest"])["enabled"] is False
    finally:
        reset_digest()


def test_tool_result_op_switch():
    reset_tool_result()
    try:
        r = _cmd_memory(["tool-result", "on"])
        assert r["success"] is True
        assert r["enabled"] is True
        r2 = _cmd_memory(["tool-result", "max_chars=2000"])
        assert r2["max_chars"] == 2000
        _cmd_memory(["tool-result", "off"])
        assert _cmd_memory(["tool-result"])["enabled"] is False
    finally:
        reset_tool_result()


def test_sensitive_op_switch():
    reset_sensitive()
    try:
        assert _cmd_memory(["sensitive"])["enabled"] is True  # default ON
        _cmd_memory(["sensitive", "off"])
        assert _cmd_memory(["sensitive"])["enabled"] is False
    finally:
        reset_sensitive()


def test_compression_guard_op_switch():
    reset_guard()
    try:
        r = _cmd_memory(["compression-guard", "threshold=5", "breaker=off"])
        assert r["success"] is True
        assert r["recursion_threshold"] == 5
        assert r["breaker_enabled"] is False
        st = _cmd_memory(["compression-guard"])
        assert st["recursion_threshold"] == 5
    finally:
        reset_guard()


def test_context_audit_op():
    reset_loop_registry()
    try:
        r = _cmd_memory(["context-audit", "cell-9"])
        assert r["success"] is True
        assert "per_agent" in r
    finally:
        reset_loop_registry()


def test_prompt_library_op_switch():
    from l3.agent.global_prompt_library import reset_global_prompt_library
    from l3.agent.prompt_library import reset_prompt_library

    reset_prompt_library()
    reset_global_prompt_library()
    try:
        r = _cmd_memory(["prompt-library", "off", "global=off"])
        assert r["success"] is True
        assert r["cell"]["enabled"] is False
        assert r["global"]["enabled"] is False
        r2 = _cmd_memory(["prompt-library"])
        assert r2["cell"]["enabled"] is False
    finally:
        reset_prompt_library()
        reset_global_prompt_library()
