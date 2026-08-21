"""Validate shared Python3/Rust value-contract vectors."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.event import Signal, SignalType
from l1.kernel.ports.process import ProcessOptions, ProcessResult
from l1.kernel.ports.types import Event
from l1.kernel.process import ProcessState
from l1.kernel.sync import RWLock

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_value_vectors.json"


def test_shared_kernel_value_vectors_match_python_reference() -> None:
    """Keep Python3 wire values aligned with the Rust contract mirror."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))

    for vector in vectors:
        kind = vector["kind"]
        value = vector["value"]
        if kind == "process_result":
            result = ProcessResult(**value)
            assert result.ok is (vector["case"] == "process_success")
        elif kind == "process_options":
            options = ProcessOptions(**value)
            assert options.cwd == "/tmp"
            assert options.executable == "/bin/sh"
        elif kind == "process_states":
            assert [state.name for state in ProcessState] == value
        elif kind == "signal":
            signal = Signal(
                type=SignalType[value["type"]],
                data=value["data"],
                sender=value["sender"],
                target=value["target"],
                timestamp=value["timestamp"],
            )
            assert signal.to_dict() == value
        elif kind == "event":
            event = Event(
                type=value["type"],
                source=value["source"],
                severity=value["severity"],
                message=value["message"],
                message_locale=value["message_locale"],
                data=value["data"],
            )
            assert event.type == value["type"]
            assert event.data == value["data"]
        elif kind == "event_bus_stats":
            attempts = value["submitted"] + value["dropped"]
            clean = value["dropped"] == 0 and value["queue_depth"] == 0 and value["completed"] == value["submitted"]
            assert clean is (vector["case"] == "event_bus_clean")
            assert (value["dropped"] / attempts if attempts else 0.0) == (
                0.0 if vector["case"] == "event_bus_clean" else 0.2
            )
        elif kind == "capability_result":
            assert value["success"] is False
            assert "fail-closed" in value["error"]
        elif kind == "rwlock":
            lock = RWLock(value["name"])
            agent_id = value["agent_id"]
            if vector["case"] == "rwlock_write_reentrant":
                assert lock.write_lock(agent_id) == value["first"]
                assert lock.write_lock(agent_id) == value["second"]
                assert lock.unlock(agent_id) == value["release_once"]
                assert lock.unlock(agent_id) == value["release_twice"]
            else:
                assert lock.read_lock(agent_id) == value["read"]
                assert lock.write_lock(agent_id) == value["write"]
                assert lock.unlock(agent_id) == value["unlock"]
            assert lock.status() == value["status"]
        else:
            raise AssertionError(f"unknown contract vector kind: {kind}")
