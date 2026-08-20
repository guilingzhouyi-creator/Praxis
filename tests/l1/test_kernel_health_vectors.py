"""Validate shared health aggregation vectors against the Python reference."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.healthcheck import aggregate_health

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_health_vectors.json"


def test_shared_health_vectors_match_python_reference() -> None:
    """Keep status precedence, counts, subsystem retention, and rounding aligned."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for case in vectors["cases"]:
        assert aggregate_health(case["subsystems"], case["elapsed_ms"]) == case["expected"], case["name"]
