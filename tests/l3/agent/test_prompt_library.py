"""Tests for the Cell-domain shared prompt library (3.2, P0-②)."""

from __future__ import annotations

from l3.agent.prompt_library import (
    get_dynamic_doc,
    get_shared_base,
    prompt_library_status,
    reset_prompt_library,
    resolve_cell_prompt,
    set_dynamic_doc,
    set_prompt_library_switches,
    set_shared_base,
)


def test_enabled_by_default():
    reset_prompt_library()
    try:
        assert prompt_library_status()["enabled"] is True
    finally:
        reset_prompt_library()


def test_shared_base_and_dynamic_doc_roundtrip():
    reset_prompt_library()
    try:
        assert set_shared_base("cell-1", "SHARED BASE") is True
        assert set_dynamic_doc("cell-1", "Agent-cell-1.md", "DYNAMIC DOC") is True
        assert get_shared_base("cell-1") == "SHARED BASE"
        assert get_dynamic_doc("cell-1", "Agent-cell-1.md") == "DYNAMIC DOC"
    finally:
        reset_prompt_library()


def test_resolve_low_pressure_returns_shared_base_only():
    reset_prompt_library()
    try:
        set_shared_base("cell-1", "SHARED BASE")
        set_dynamic_doc("cell-1", "Agent-cell-1.md", "DYNAMIC DOC")
        text = resolve_cell_prompt("cell-1", pressure=0.3)
        assert text == "SHARED BASE"
    finally:
        reset_prompt_library()


def test_resolve_high_pressure_appends_dynamic_doc():
    reset_prompt_library()
    try:
        set_shared_base("cell-1", "SHARED BASE")
        set_dynamic_doc("cell-1", "Agent-cell-1.md", "DYNAMIC DOC")
        text = resolve_cell_prompt("cell-1", pressure=0.9)
        assert "SHARED BASE" in text
        assert "DYNAMIC DOC" in text
    finally:
        reset_prompt_library()


def test_disabled_returns_empty():
    reset_prompt_library()
    try:
        set_shared_base("cell-1", "SHARED BASE")
        set_prompt_library_switches(enabled=False)
        assert resolve_cell_prompt("cell-1", pressure=0.9) == ""
    finally:
        reset_prompt_library()


def test_user_writes_rejected_system_managed():
    """Only system callers may write the library (user edits forbidden)."""
    reset_prompt_library()
    try:
        assert set_shared_base("cell-1", "X", source="user") is False
        assert set_dynamic_doc("cell-1", "Agent-cell-1.md", "Y", source="user") is False
        assert get_shared_base("cell-1") == ""
        assert get_dynamic_doc("cell-1", "Agent-cell-1.md") == ""
        # System writes still work.
        assert set_shared_base("cell-1", "SYSTEM", source="system") is True
        assert get_shared_base("cell-1") == "SYSTEM"
    finally:
        reset_prompt_library()
