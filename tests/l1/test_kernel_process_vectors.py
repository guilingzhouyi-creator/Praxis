"""Validate shared process-table mechanism vectors against Python."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.process import ProcessTable

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_process_vectors.json"


def _project_pcb(pcb) -> dict:
    """Return deterministic PCB fields without clock-derived snapshot values."""
    return {
        "pid": pcb.pid,
        "name": pcb.name,
        "role": pcb.role,
        "parent_pid": pcb.parent_pid,
        "ring": pcb.ring,
        "state": pcb.state.name,
        "identity_verified": pcb.identity_verified,
        "cancelled": pcb.cancelled,
        "cancel_reason": pcb.cancel_reason,
        "exit_code": pcb.exit_code,
        "exit_reason": pcb.exit_reason,
        "resources": pcb.resources.__dict__.copy(),
    }


def _project_audit(rows: list[dict]) -> list[dict]:
    """Remove wall-clock timestamps from audit rows while retaining order."""
    return [{key: row[key] for key in ("op", "pid", "name", "detail")} for row in rows]


def test_shared_process_vectors_match_python_reference() -> None:
    """Keep lifecycle, cancellation, resource accounting, and audit order aligned."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for case in vectors["cases"]:
        table = ProcessTable(gc_interval=9999)
        before_reap = None
        for operation in case["operations"]:
            kind = operation["kind"]
            if kind == "spawn":
                pcb = table.spawn(
                    operation["name"],
                    role=operation["role"],
                    parent_pid=operation["parent_pid"],
                    ring=operation["ring"],
                )
                assert pcb.pid == operation["pid"]
            elif kind == "mark_identity_verified":
                assert table.mark_identity_verified(operation["name"])
            elif kind == "record_tokens":
                pcb = table.get(operation["pid"])
                assert pcb is not None
                pcb.record_tokens(operation["allocated"], operation["used"])
            elif kind == "record_card":
                pcb = table.get(operation["pid"])
                assert pcb is not None
                pcb.record_card()
            elif kind == "record_scout":
                pcb = table.get(operation["pid"])
                assert pcb is not None
                pcb.record_scout(operation["delta"])
            elif kind == "record_cpu":
                pcb = table.get(operation["pid"])
                assert pcb is not None
                pcb.record_cpu(operation["seconds"])
            elif kind == "record_alloc":
                pcb = table.get(operation["pid"])
                assert pcb is not None
                pcb.record_alloc(operation["tokens"])
            elif kind == "record_use":
                pcb = table.get(operation["pid"])
                assert pcb is not None
                pcb.record_use(operation["tokens"], operation["cpu_seconds"])
            elif kind == "set_running":
                assert table.set_running(operation["name"]) is operation["result"]
            elif kind == "yield":
                assert table.yield_process(operation["name"])
            elif kind == "cancel":
                assert table.cancel(operation["name"], operation["reason"])
            elif kind == "exit_by_name":
                assert table.exit_by_name(operation["name"], operation["exit_code"], operation["reason"])
            elif kind == "reap":
                before_reap = _project_pcb(table.get(operation["pid"]))
                assert table.reap(operation["pid"]) is not None
            else:
                raise AssertionError(f"unknown process operation: {kind}")

        expected = case["expected"]
        if before_reap is None:
            assert _project_pcb(table.get_by_name(expected["agent"]["name"])) == expected["agent"]
            assert table.is_cancelled(expected["agent"]["name"]) is expected["is_cancelled"]
            assert table.set_running(expected["agent"]["name"]) is expected["final_set_running"]
        else:
            for key, value in expected["before_reap"].items():
                assert before_reap[key] == value
            assert table.get_by_name(expected["before_reap"]["name"]) is None
            assert expected["after_reap_exists"] is False
        assert table.resource_summary() == expected["resource_summary"]
        assert _project_audit(table.audit_log(20)) == expected["audit"]
        table.stop()
