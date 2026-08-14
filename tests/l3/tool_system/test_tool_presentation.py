"""Tests for tool_presentation — Code Mode / PTC presentation switch.

Covers the native/code/both three-state runtime switch, the language-agnostic
CodeRenderer seam, the shipped Python renderer (deterministic SDK output),
and the per-Cell program cache directory resolution.
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


def test_python_renderer_registered():
    renderer = tp.get_renderer()
    assert renderer is not None
    assert renderer.language == "python"


def test_sdk_render_deterministic_and_order_independent():
    renderer = tp.get_renderer()
    tools = [
        {"name": "grep_search", "description": "Search contents", "parameters": []},
        {"name": "read_file", "description": "Read a file", "parameters": [{"name": "path", "type": "string"}]},
    ]
    first = renderer.render_sdk(tools)
    second = renderer.render_sdk(tools)
    assert first == second  # byte-stable for vendor prefix caching
    assert first == renderer.render_sdk(list(reversed(tools)))  # sorted output


def test_usage_instructions_stable():
    renderer = tp.get_renderer()
    assert renderer.render_usage() == renderer.render_usage()


def test_cell_program_dir_namespaced():
    import os

    d1 = str(tp.cell_program_dir("cell-x"))
    d2 = str(tp.cell_program_dir("cell-y"))
    assert "cell-x" in d1 and "cell-y" in d2
    assert d1 != d2
    assert "praxis-toolpres" in d1
    # No filesystem side effect: the path is resolved lazily, not created here.
    assert not os.path.exists(d1)


def test_status_reports_renderers():
    tp.set_presentation_mode("code", source="test")
    status = tp.presentation_status()
    assert status["mode"] == "code"
    assert "python" in status["renderers"]
    tp.reset_presentation_mode()
