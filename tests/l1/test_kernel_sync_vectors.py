"""Validate shared RWLock mechanism vectors against Python3."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.sync import RWLock

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_sync_vectors.json"


def test_shared_rwlock_vectors_match_python_reference() -> None:
    """Keep reentrant reads, bounded timeout, and unlock errors aligned."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for case in vectors["cases"]:
        lock = RWLock(case["lock_name"])
        timeout = case["timeout_ms"] / 1000
        for operation in case["operations"]:
            if operation["kind"] == "read":
                actual = lock.read_lock(operation["agent"], timeout=timeout)
            elif operation["kind"] == "write":
                actual = lock.write_lock(operation["agent"], timeout=timeout)
            elif operation["kind"] == "unlock":
                actual = lock.unlock(operation["agent"])
            else:
                raise AssertionError(f"unknown sync operation: {operation['kind']}")
            assert actual == operation["expected"], case["name"]
            assert lock.status() == operation["status"], case["name"]
