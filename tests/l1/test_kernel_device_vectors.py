"""Validate deterministic device bookkeeping vectors against Python3."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.device import DeviceHealth, DeviceManager, DeviceType

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_device_vectors.json"


def test_shared_device_vectors_match_rust_candidate() -> None:
    """Keep rate windows, health thresholds, summaries, and stats aligned."""
    vector = json.loads(_VECTORS.read_text(encoding="utf-8"))
    manager = DeviceManager()
    for operation in vector["operations"]:
        op = operation["op"]
        name = operation.get("name", "")
        if op == "register":
            device = operation["device"]
            actual = manager.register(
                device["name"],
                DeviceType[device["device_type"]],
                rate_limit=device["rate_limit"],
                rate_window=device["rate_window"],
                description=device.get("description", ""),
                capabilities=device.get("capabilities", []),
                version=device.get("version", ""),
            )["success"]
        elif op == "check_rate":
            actual = manager.check_rate(name, now=operation["now"])
        elif op == "record_call":
            manager.record_call(name, success=operation.get("success", True), now=operation["now"])
            actual = None
        elif op == "record_many":
            for _ in range(operation["count"]):
                manager.record_call(name, success=operation.get("success", True), now=operation["now"])
            actual = None
        elif op == "refresh_health":
            manager._check_all_health()
            actual = None
        elif op == "set_health":
            actual = manager.set_health(name, DeviceHealth[operation["health"]])
        elif op == "list":
            actual = manager.list()
        elif op == "stats":
            actual = manager.stats()
        elif op == "unregister":
            actual = manager.unregister(name)
        else:
            raise AssertionError(f"unknown device vector operation: {op}")
        assert actual == operation["expected"], op
