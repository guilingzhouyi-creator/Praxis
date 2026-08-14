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


def test_run_code_rejects_unregistered_language():
    # TypeScript is a roadmap slot with no backend registered yet — the
    # handler must reject gracefully, listing the available backends (never
    # a hardcoded "unsupported language" branch tied to Python).
    result = run_code({"program": "console.log(1)", "language": "typescript", "cell_id": "cell-t"}, agent_id="tester")
    assert result["success"] is False
    assert "no language backend" in result["error"]
    assert "python" in result["error"]  # available backends are listed


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


def test_run_code_wires_bindings_to_pipeline():
    """Python programs run in-process: SDK bindings execute the real tool.

    ``_praxis_call`` must route through the pipeline (audit chain), not be a
    no-op stub — a call to an unregistered tool surfaces the pipeline result.
    """
    reset_run_code_cache()
    try:
        # read_file is not registered in this unit context, but the binding
        # must still execute through the pipeline (UNKNOWN/error surfaced).
        result = run_code(
            {
                "program": 'r = _praxis_call("read_file", path="/tmp/nope.txt")\nprint("done", r.get("success"))',
                "cell_id": "cell-wire",
            },
            agent_id="w",
        )
        assert result["success"] is True
        assert result.get("bindings_wired") is True
        assert "done" in result["result"]
    finally:
        reset_run_code_cache()


def test_run_code_binding_parent_chain_linked():
    """The binding call inherits the run_code call as parent on the chain.

    In production the pipeline wraps the run_code handler in
    ``trace_scope(call_id)``; here we simulate that scope so the binding's
    parent id resolves to the run_code call id.
    """
    from l1.kernel.tool_chain import get_tool_chain, reset_tool_chain
    from l3.error_bus.trace import trace_scope

    reset_tool_chain()
    reset_run_code_cache()
    try:
        with trace_scope("rc-parent"):
            run_code(
                {"program": '_praxis_call("read_file", path="/tmp/x")', "cell_id": "cell-pc"},
                agent_id="w",
            )
        chain = get_tool_chain()
        calls = chain.recent(limit=10)
        names = [c["tool"] for c in calls]
        assert "read_file" in names
        rf = next(c for c in calls if c["tool"] == "read_file")
        assert rf["call_id"].startswith("rc-parent") or rf["depth"] >= 1
    finally:
        reset_run_code_cache()
        reset_tool_chain()


def test_run_code_writes_back_successful_result_to_cache():
    """A successful run_code caches program + result for later reuse."""
    reset_run_code_cache()
    try:
        result = run_code({"program": "print(6 * 7)", "cell_id": "cell-wb"}, agent_id="w")
        assert result["success"] is True
        assert result.get("cached_writeback") is True
        cache = get_run_code_cache()
        entry = cache.lookup("cell-wb", "print(6 * 7)")
        assert entry is not None
        assert entry["result"] == "42\n"
        assert entry["language"] == "python"
    finally:
        reset_run_code_cache()


def test_run_code_does_not_cache_failure():
    """Failed programs are not cached (only successful results are)."""
    reset_run_code_cache()
    try:
        result = run_code({"program": 'raise ValueError("boom")', "cell_id": "cell-wb2"}, agent_id="w")
        assert result["success"] is False
        cache = get_run_code_cache()
        assert cache.lookup("cell-wb2", 'raise ValueError("boom")') is None
    finally:
        reset_run_code_cache()


def test_pipeline_code_only_rejects_native_tools():
    """tools:code-only — code presentation blocks native tool names."""
    from l3.tool_system.tool_pipeline import get_pipeline, reset_pipeline
    from l3.tool_system.tool_presentation import reset_presentation_mode, set_presentation_mode

    def executor(*_a, **_k):
        return {"success": True}

    p = get_pipeline()
    try:
        # native (default): read_file is not blocked by code-only.
        r = p.execute("read_file", "tester", {"path": "x"}, _registry={}, _executor=executor)
        assert "UNKNOWN_TOOL" not in str(r.get("error", ""))

        # code: native names resolve to UNKNOWN_TOOL before gating.
        set_presentation_mode("code", source="test")
        r2 = p.execute("read_file", "tester", {"path": "x"}, _registry={}, _executor=executor)
        assert r2.get("success") is False
        assert "UNKNOWN_TOOL" in r2.get("error", "")

        # code: run_code itself is allowed through.
        r3 = p.execute("run_code", "tester", {"program": "print(1)"}, _registry={}, _executor=executor)
        assert "UNKNOWN_TOOL" not in str(r3.get("error", ""))
    finally:
        reset_presentation_mode()
        reset_pipeline()


def test_pipeline_code_only_both_mode_unrestricted():
    """both presentation keeps native schemas AND the transport."""
    from l3.tool_system.tool_pipeline import get_pipeline, reset_pipeline
    from l3.tool_system.tool_presentation import reset_presentation_mode, set_presentation_mode

    def executor(*_a, **_k):
        return {"success": True}

    p = get_pipeline()
    try:
        set_presentation_mode("both", source="test")
        r = p.execute("read_file", "tester", {"path": "x"}, _registry={}, _executor=executor)
        assert "UNKNOWN_TOOL" not in str(r.get("error", ""))
    finally:
        reset_presentation_mode()
        reset_pipeline()
