"""KernelSchedulerPort (W6.2) — mechanism seam + kernel syscall notification."""

from __future__ import annotations

from l1.kernel import syscall
from l1.kernel.ports import KernelSchedulerPort, get_port, register_port, reset_ports


def test_central_scheduler_implements_port() -> None:
    """The L3 CentralScheduler must satisfy the kernel port contract."""
    from l3.scheduler.scheduler import CentralScheduler

    s = CentralScheduler()
    assert isinstance(s, KernelSchedulerPort)
    s.router.register("port-agent", ["test"])
    # concrete primitives exist and behave
    r = s.submit("test", "probe", args={}, priority=1)
    assert r.get("success") is True, r
    tid = r["task_id"]
    pr = s.preempt(tid, reason="w6.2 probe")
    assert pr.get("success") is True, pr
    st = s.status(tid)
    assert "preempted" in st.get("error", "")
    assert isinstance(s.stats(), dict)


def test_port_wired_at_boot_defaults() -> None:
    """wire_defaults registers the scheduler under port name 'scheduler'."""
    from l3.boot.wiring import wire_defaults

    wire_defaults()
    port = get_port("scheduler")
    assert isinstance(port, KernelSchedulerPort)
    reset_ports()


def test_syscall_notifies_scheduler_port() -> None:
    """process.spawn/exit/cancel reach the port's notify_event (W6.2)."""
    events: list[tuple[str, dict]] = []

    class _FakeScheduler(KernelSchedulerPort):
        def submit(self, domain, command, args=None, intent_tags=None, preferred_agent=None, priority=0):
            return {"success": True, "task_id": "t"}

        def poll(self):
            return None

        def preempt(self, task_id, reason=""):
            return {"success": True}

        def notify_event(self, event, data=None):
            events.append((event, data or {}))

        def stats(self):
            return {}

    register_port("scheduler", _FakeScheduler())
    try:
        syscall("process.spawn", agent_id="sp-agent", name="sp-agent", role="test")
        syscall("process.cancel", agent_id="sp-agent", name="sp-agent", reason="port test")
    finally:
        reset_ports()
    names = [e for e, _ in events]
    assert "process.spawn" in names
    assert "process.cancel" in names
