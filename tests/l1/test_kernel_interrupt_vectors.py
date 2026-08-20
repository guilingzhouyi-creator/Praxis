"""Validate shared interrupt bookkeeping vectors against the Python reference."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.interrupt import InterruptTable, InterruptType

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_interrupt_vectors.json"


def test_shared_interrupt_vectors_match_python_reference() -> None:
    """Keep IRQ names, counters, sequence numbers, and history wire shape aligned."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for vector in vectors:
        table = InterruptTable()
        for event in vector["events"]:
            table.fire(
                InterruptType[event["type"]],
                agent_id=event.get("agent_id", ""),
                reason=event.get("reason", ""),
                data=event.get("data"),
            )
        assert table.counts() == vector["expected_counts"], vector["case"]
        assert table.recent(vector["recent_limit"]) == vector["expected_recent"], vector["case"]
