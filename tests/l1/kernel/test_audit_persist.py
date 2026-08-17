"""Kernel audit — durable journal persistence (W4.1)."""

from __future__ import annotations

import os
import tempfile
import time


def _marker() -> str:
    """Unique detail marker for this test run."""
    return f"audit-persist-{time.time_ns()}"


def _isolated_db() -> None:
    """Point the event store at a private temp DB for this test.

    The production store is a single shared SQLite file; under parallel
    xdist workers, other tests append to it concurrently, so a shared-DB
    assertion can hit spurious lock / I-O / LIMIT-truncation errors. A
    private DB per test keeps the flush→persist contract deterministic.
    """
    from l1.kernel import persist as _persist

    _persist.reset_persist()
    _persist._DB_PATH = os.path.join(tempfile.mkdtemp(prefix="audit-persist-"), "events.db")


def test_record_audit_persists_on_flush() -> None:
    """Flushed audit entries must land in the persist journal."""
    from l1.kernel import flush_audit_buffer, record_audit
    from l1.kernel.persist import query

    _isolated_db()
    marker = _marker()
    record_audit("test.audit", "audit-probe", success=True, detail=marker)
    flush_audit_buffer()

    rows = [r for r in query("audit.syscall", limit=1000) if r["payload"].get("detail") == marker]
    assert rows, "marker not persisted"


def test_audit_persist_payload_shape() -> None:
    """Persisted entries keep the syscall-audit field contract."""
    from l1.kernel import flush_audit_buffer, record_audit
    from l1.kernel.persist import query

    _isolated_db()
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
