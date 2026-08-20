"""Validate shared memory-ring planning vectors against the Python reference."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.swapper import plan_compaction, plan_pressure, plan_swap_out

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_swapper_vectors.json"


def test_shared_swapper_vectors_match_python_reference() -> None:
    """Keep ring routing, compaction filters, and pressure gates aligned."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for case in vectors["cases"]:
        actual_swap = plan_swap_out(case["entries"], count=case.get("count"))
        actual_compaction = plan_compaction(case["entries"])
        assert actual_swap == case["expected_swap_out"], case["name"]
        assert actual_compaction == case["expected_compaction"], case["name"]
    for case in vectors["pressure"]:
        assert plan_pressure(case["snapshot"], high_threshold=case["high_threshold"]) == case["expected"], case["name"]
