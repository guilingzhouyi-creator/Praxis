"""Cross-language dependency vectors for the Python boot registry adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_shared_boot_plan_vectors_match_python_registry():
    """Keep valid/cycle ordering visible while recording Python's missing-dependency behavior."""
    from l3.boot.boot_registry import register_boot_step, reset_registry, resolve_boot_order

    vectors = json.loads(Path("tests/fixtures/kernel_boot_plan_vectors.json").read_text(encoding="utf-8"))
    reset_registry()
    try:
        for step in vectors["valid_steps"]:
            register_boot_step(step["name"], lambda: {"success": True}, depends_on=step["depends_on"])
        assert resolve_boot_order() == vectors["expected_order"]

        reset_registry()
        for step in vectors["cycle_steps"]:
            register_boot_step(step["name"], lambda: {"success": True}, depends_on=step["depends_on"])
        with pytest.raises(RuntimeError, match="circular boot dependency"):
            resolve_boot_order()

        reset_registry()
        for step in vectors["missing_steps"]:
            register_boot_step(step["name"], lambda: {"success": True}, depends_on=step["depends_on"])
        assert resolve_boot_order() == vectors["python_missing_order"]
    finally:
        reset_registry()
