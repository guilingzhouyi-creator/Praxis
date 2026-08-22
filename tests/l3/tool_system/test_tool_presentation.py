"""Tests for tool_presentation — Code Mode / PTC presentation switch.

Covers the native/code/both three-state runtime switch, the language-agnostic
CodeLanguageBackend composite (SDK render / usage / file suffix / execute),
the shipped Python backend (deterministic SDK output), the graceful rejection
of unregistered languages, and the per-Cell program cache directory.
"""

from __future__ import annotations

from l3.tool_system import tool_presentation as tp


def test_default_mode_is_native():
    assert tp.get_presentation_mode() == "native"


def test_set_valid_modes():
    for mode in ("code", "both", "native"):
        assert tp.set_presentation_mode(mode, source="test")["success"] is True
        assert tp.get_presentation_mode() == mode


def test_set_invalid_mode_rejected():
    result = tp.set_presentation_mode("bogus")
    assert result["success"] is False
    assert "invalid" in result["error"]


def test_reset_returns_to_config():
    tp.set_presentation_mode("code", source="test")
    tp.reset_presentation_mode()
    assert tp.get_presentation_mode() == "native"


def test_python_backend_registered_and_aliased():
    backend = tp.get_language_backend()
    assert backend is not None
    assert backend.language == "python"
    # Backward-compatible alias resolves to the same backend instance.
    assert tp.get_renderer() is backend


def test_backend_file_suffix():
    backend = tp.get_language_backend("python")
    assert backend.file_suffix == ".py"


def test_unregistered_language_returns_none():
    # TypeScript is a roadmap slot — not yet registered, must be None
    # (the run_code handler then rejects it gracefully listing available).
    assert tp.get_language_backend("typescript") is None
    assert tp.get_language_backend("rust") is None


def test_sdk_render_deterministic_and_order_independent():
    backend = tp.get_language_backend()
    tools = [
        {"name": "grep_search", "description": "Search contents", "parameters": []},
        {"name": "read_file", "description": "Read a file", "parameters": [{"name": "path", "type": "string"}]},
    ]
    first = backend.render_sdk(tools)
    second = backend.render_sdk(tools)
    assert first == second  # byte-stable for vendor prefix caching
    assert first == backend.render_sdk(list(reversed(tools)))  # sorted output


def test_usage_instructions_stable():
    backend = tp.get_language_backend()
    assert backend.render_usage() == backend.render_usage()


def test_backend_execute_runs_python_program():
    import tempfile
    from pathlib import Path

    backend = tp.get_language_backend("python")
    prog = Path(tempfile.mkdtemp()) / "prog.py"
    prog.write_text("print(40 + 2)", encoding="utf-8")
    result = backend.execute(prog, timeout=30)
    assert result.returncode == 0
    assert result.stdout.strip() == "42"


def test_cell_program_dir_namespaced():
    import os

    d1 = str(tp.cell_program_dir("cell-x"))
    d2 = str(tp.cell_program_dir("cell-y"))
    assert "cell-x" in d1 and "cell-y" in d2
    assert d1 != d2
    assert "praxis-toolpres" in d1
    # No filesystem side effect: the path is resolved lazily, not created here.
    assert not os.path.exists(d1)


def test_status_reports_languages_and_legacy_key():
    tp.set_presentation_mode("code", source="test")
    status = tp.presentation_status()
    assert status["mode"] == "code"
    assert "python" in status["languages"]
    assert status["languages"] == status["renderers"]  # legacy alias
    tp.reset_presentation_mode()
