"""Process FSM driving, cancellation and handle registration (WS3)."""

from __future__ import annotations

from l1.kernel.interrupt import get_table as get_interrupt_table
from l1.kernel.process import ProcessState, get_table


def _spawn(name: str) -> int:
    """Spawn a fresh process and return its pid."""
    return get_table().spawn(name, role="test", ring=2).pid


def test_fsm_run_yield_cycle() -> None:
    """Card execution drives READY -> RUNNING -> READY (W3.1)."""
    pid = _spawn("fsm-agent")
    pt = get_table()
    pcb = pt.get(pid)
    assert pcb.state is ProcessState.READY
    assert pt.set_running("fsm-agent") is True
    assert pcb.state is ProcessState.RUNNING
    # idempotent while running
    assert pt.set_running("fsm-agent") is True
    assert pt.yield_process("fsm-agent") is True
    assert pcb.state is ProcessState.READY


def test_fsm_exit_by_name_and_reap() -> None:
    """Session shutdown exits the PCB; the reaper can reap it (W3.1)."""
    pid = _spawn("fsm-exit")
    pt = get_table()
    assert pt.exit_by_name("fsm-exit", exit_code=3, reason="shutdown") is True
    pcb = pt.get(pid)
    assert pcb.state is ProcessState.ZOMBIE
    assert pcb.exit_code == 3
    assert pt.reap(pid) is not None
    assert pt.get(pid) is None


def test_cancel_marks_stopped_and_fires_interrupt() -> None:
    """Cancel sets the flag, STOPPED state and a CANCELLED interrupt (W3.2)."""
    pid = _spawn("cancel-agent")
    pt = get_table()
    assert pt.is_cancelled("cancel-agent") is False
    assert pt.cancel("cancel-agent", reason="user abort") is True
    pcb = pt.get(pid)
    assert pcb.cancelled is True
    assert pcb.cancel_reason == "user abort"
    assert pcb.state is ProcessState.STOPPED
    assert pt.is_cancelled("cancel-agent") is True
    counts = get_interrupt_table().counts()
    assert counts.get("CANCELLED", 0) >= 1
    # cancelling again stays consistent (idempotent)
    assert pt.cancel("cancel-agent", reason="again") is True
    assert pt.is_cancelled("cancel-agent") is True


def test_cancel_via_syscall() -> None:
    """process.cancel is reachable through the syscall surface (W3.2)."""
    _spawn("syscancel-agent")
    from l1.kernel import syscall

    r = syscall("process.cancel", agent_id="syscancel-agent", name="syscancel-agent", reason="syscall abort")
    assert r["success"] is True
    assert get_table().is_cancelled("syscancel-agent") is True


def test_handle_registration_and_liveness() -> None:
    """Long-lived OS handles register and report liveness (W3.3)."""
    pt = get_table()

    class _FakeProc:
        def poll(self):
            return None  # alive

    class _DeadProc:
        def poll(self):
            return 0  # exited

    hid1 = pt.register_handle("proc-a", _FakeProc())
    hid2 = pt.register_handle("proc-b", _DeadProc())
    assert hid1 != hid2
    by_id = {h["id"]: h for h in pt.list_handles()}
    assert by_id[hid1]["alive"] is True
    assert by_id[hid2]["alive"] is False
    assert by_id[hid1]["name"] == "proc-a"
