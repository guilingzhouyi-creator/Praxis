"""Validate shared RingChannel mechanism vectors against Python."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.channel_ring import RingChannel

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_channel_vectors.json"


def test_shared_channel_vectors_match_python_reference() -> None:
    """Keep FIFO, overload, overwrite, drain, and close semantics aligned."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for case in vectors["cases"]:
        channel = RingChannel(capacity=case["capacity"], overwrite=case["overwrite"])
        for operation in case["operations"]:
            kind = operation["kind"]
            timeout = operation.get("timeout_ms", 0) / 1000
            if kind == "put":
                actual = channel.put(operation["value"], timeout=timeout)
            elif kind == "get":
                actual = channel.get(timeout=timeout)
            elif kind == "peek":
                actual = channel.peek(timeout=timeout)
            elif kind == "size":
                actual = channel.size()
            elif kind == "drain":
                actual = channel.drain()
            elif kind == "utilization":
                actual = channel.utilization()
            elif kind == "close":
                channel.close()
                actual = None
            else:
                raise AssertionError(f"unknown channel operation: {kind}")
            assert actual == operation["expected"], case["name"]
        assert channel.is_closed() is case["expected_closed"], case["name"]
