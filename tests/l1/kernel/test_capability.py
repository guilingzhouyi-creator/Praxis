"""l1/kernel/capability — invoke-capability syscall (W6.1)."""

from __future__ import annotations

import pytest

from l1.kernel.capability import (
    has_capability_executor,
    invoke_capability,
    register_capability_executor,
    reset_capability_executor,
)


@pytest.fixture(autouse=True)
def _no_executor() -> None:
    """Start every test with the execution authority unwired."""
    reset_capability_executor()
    yield
    reset_capability_executor()


def test_unwired_fail_closed() -> None:
    """No wired executor -> every call is denied (fail-closed)."""
    r = invoke_capability("user:x", "read_file", {"path": "/tmp/x"}, interactive=True)
    assert r.get("success") is False
    assert "fail-closed" in r.get("error", "")


def test_unwired_denial_audited() -> None:
    """Denied invocations still land in the kernel audit trail."""
    from l1.kernel import get_audit_log

    invoke_capability("user:x", "read_file", {}, interactive=True)
    log = get_audit_log(agent_id="user:x")
    assert any(e.get("op") == "capability.invoke" and not e.get("success") for e in log)


def test_wired_passes_through_and_audits() -> None:
    """The wired executor receives the full call and the result is audited."""
    from l1.kernel import get_audit_log

    calls: list[tuple] = []

    def _exec(name, args, agent_id="", domain="", nature="", interactive=False):
        calls.append((name, args, agent_id, domain, nature, interactive))
        return {"success": True, "result": {"data": args}}

    register_capability_executor(_exec)
    r = invoke_capability("user:x", "read_file", {"path": "/tmp/x"}, domain="d", nature="n", interactive=True)
    assert r.get("success") is True
    assert calls == [("read_file", {"path": "/tmp/x"}, "user:x", "d", "n", True)]
    log = get_audit_log(agent_id="user:x")
    assert any(e.get("op") == "capability.invoke" and e.get("success") for e in log)


def test_wired_failure_audited() -> None:
    """Executor failures are audited with the error text."""
    from l1.kernel import get_audit_log

    def _exec(name, args, agent_id="", domain="", nature="", interactive=False):
        return {"success": False, "error": "nope"}

    register_capability_executor(_exec)
    r = invoke_capability("user:x", "read_file", {})
    assert r.get("success") is False
    log = get_audit_log(agent_id="user:x")
    assert any(e.get("op") == "capability.invoke" and not e.get("success") and e.get("error") == "nope" for e in log)


def test_has_executor_flag() -> None:
    """has_capability_executor reflects the wiring state."""
    assert has_capability_executor() is False
    register_capability_executor(lambda **kw: {})
    assert has_capability_executor() is True
