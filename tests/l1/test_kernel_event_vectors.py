"""Validate deterministic EventBus history vectors against Python."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.event import EventBus, Signal, SignalType

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_event_vectors.json"


def test_shared_event_history_vectors_match_python_reference() -> None:
    """Keep bounded history, filters, serialization, and idle counters aligned."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for case in vectors["cases"]:
        bus = EventBus(max_history=case["max_history"])
        for raw in case["signals"]:
            signal = Signal(
                type=SignalType[raw["type"]],
                data=raw["data"],
                sender=raw["sender"],
                target=raw["target"],
                timestamp=raw["timestamp"],
            )
            assert bus.emit(signal) == 0, case["name"]
        assert bus.history(limit=10) == case["expected_history"], case["name"]
        assert bus.history(SignalType.TASK_DONE, limit=10) == case["expected_task_history"], case["name"]
        assert bus.history(SignalType.REVIEW_RESULT, limit=10) == case["expected_review_history"], case["name"]
        stats = bus.stats()
        assert {key: stats[key] for key in case["expected_stats"]} == case["expected_stats"], case["name"]
        bus.shutdown(wait=True, timeout=1.0)
