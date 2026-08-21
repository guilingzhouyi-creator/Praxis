"""Validate shared load-adaptive control-law vectors against Python3."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.load_adaptive import ControllerMetrics, LoadAdaptiveController

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_load_adaptive_vectors.json"


def test_shared_load_adaptive_vectors_match_python_reference() -> None:
    """Keep Rust and Python3 decisions aligned for fixed timestamps and metrics."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for case in vectors["cases"]:
        controller = LoadAdaptiveController(**case["config"])
        for step in case["steps"]:
            actual = controller.decide(ControllerMetrics(**step["metrics"]), now=step["now"])
            expected = step["expected"]
            assert actual.action.name == expected["action"]
            assert actual.target_workers == expected["target_workers"]
            assert actual.ewma_depth == expected["ewma_depth"]
            assert actual.in_cooldown is expected["in_cooldown"]
            assert actual.reason == expected["reason"]
