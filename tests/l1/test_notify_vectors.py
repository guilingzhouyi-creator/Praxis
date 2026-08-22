"""Run shared notification-buffer vectors against the Python reference adapter."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.notify import LocalNotifyAdapter


def test_shared_notify_vectors_match_python_reference() -> None:
    """Python local notifications retain bounded newest-first payloads."""
    path = Path(__file__).parents[1] / "fixtures" / "kernel_notify_vectors.json"
    vectors = json.loads(path.read_text(encoding="utf-8"))
    adapter = LocalNotifyAdapter(capacity=vectors["capacity"])
    for event in vectors["events"]:
        adapter.broadcast(event["topic"], event["payload"])
    actual = [{"topic": item["topic"], "payload": item["payload"]} for item in adapter.recent()]
    assert actual == vectors["expected_recent"]
