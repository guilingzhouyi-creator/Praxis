"""Tests for run_code — the Code Mode / PTC tool transport.

Covers program execution, validation (empty / oversized / unsupported
language), timeout handling, and the per-Cell cache reuse path (approximate
similarity hit renews TTL and skips re-execution).
"""

from __future__ import annotations

from l3.tool_system.run_code_cache import get_run_code_cache, reset_run_code_cache
from l3.tools._run_code import run_code


def test_run_code_executes_program():
    result = run_code({"program": "print(40 + 2)", "cell_id": "cell-t"}, agent_id="tester")
    assert result["success"] is True
    assert result["result"] == "42\n"


def test_run_code_requires_program():
    result = run_code({"program": "", "cell_id": "cell-t"}, agent_id="tester")
    assert result["success"] is False
    assert "required" in result["error"]


def test_run_code_rejects_oversized_program():
    big = "x" * (16_000 + 1)
    result = run_code({"program": big, "cell_id": "cell-t"}, agent_id="tester")
    assert result["success"] is False
    assert "exceeds" in result["error"]


def test_run_code_rejects_unsupported_language():
    result = run_code({"program": "print(1)", "language": "typescript", "cell_id": "cell-t"}, agent_id="tester")
    assert result["success"] is False
    assert "unsupported language" in result["error"]


def test_run_code_times_out_on_hot_loop():
    result = run_code({"program": "while True: pass", "cell_id": "cell-t"}, agent_id="tester")
    assert result["success"] is False
    assert "timed out" in result["error"]


def test_run_code_returns_cache_dir():
    result = run_code({"program": "print(1)", "cell_id": "cell-t"}, agent_id="tester")
    assert "cache_dir" in result
    assert "cell-t" in result["cache_dir"]


def test_cache_hit_reuses_stored_program():
    reset_run_code_cache()
    cache = get_run_code_cache()
    cache.store("cell-t", 'def main():\n    print("analyze repo")', {"result": "analyzed"})
    # Approximate variant triggers the cached path (no execution).
    result = run_code({"program": 'def main():\n    print("analyze repo now")', "cell_id": "cell-t"}, agent_id="t")
    assert result["success"] is True
    assert result.get("cached") is True
    assert "incremental patch" in result.get("note", "")
    reset_run_code_cache()


def test_cache_miss_executes_fresh_program():
    reset_run_code_cache()
    cache = get_run_code_cache()
    cache.store("cell-t", 'def main():\n    print("analyze repo")', {"result": "analyzed"})
    result = run_code({"program": "print(7 * 6)", "cell_id": "cell-t"}, agent_id="t")
    assert result["success"] is True
    assert result.get("cached") is not True
    assert result["result"] == "42\n"
    reset_run_code_cache()
