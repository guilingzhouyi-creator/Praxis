"""Kernel audit — durable journal persistence (W4.1)."""

from __future__ import annotations

import time


def _marker() -> str:
    """Unique detail marker for this test run."""
    return f"audit-persist-{time.time_ns()}"


def test_record_audit_persists_on_flush() -> None:
    """Flushed audit entries must land in the persist journal."""
    from l1.kernel import flush_audit_buffer, record_audit
    from l1.kernel.persist import count, query

    marker = _marker()
    before = count("audit.syscall")
    record_audit("test.audit", "audit-probe", success=True, detail=marker)
    flush_audit_buffer()

    rows = query("audit.syscall", limit=200)
    assert len(rows) >= before + 1, "journal did not grow"
    assert any(r["payload"].get("detail") == marker for r in rows), "marker not persisted"


def test_audit_persist_payload_shape() -> None:
    """Persisted entries keep the syscall-audit field contract."""
    from l1.kernel import flush_audit_buffer, record_audit
    from l1.kernel.persist import query

    marker = _marker()
    record_audit("test.audit", "audit-probe", success=False, error="boom", detail=marker)
    flush_audit_buffer()
    rows = [r for r in query("audit.syscall", limit=500) if r["payload"].get("detail") == marker]
    assert rows, "marker missing from journal"
    p = rows[-1]["payload"]
    assert p["op"] == "test.audit"
    assert p["agent_id"] == "audit-probe"
    assert p["success"] is False
    assert p["error"] == "boom"
