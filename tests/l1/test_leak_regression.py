"""Regression tests for L1 memory-leak / lifecycle-hygiene fixes.

Covers:
  - Timed-out sync waiters no longer linger (Mutex/Semaphore/Barrier).
  - LockChannel backlog is bounded and requests drain their message.
  - Process reaping releases allocator / resource-limiter accounting.
  - ThreadPoolWorker retire is idempotent (no leaked spin threads).
  - SystemBus.off() actually unsubscribes handlers.
"""

from __future__ import annotations

import threading

import pytest

from l1.kernel.bus import SystemBus
from l1.kernel.ipc import LockChannel, LockMessage, LockOp
from l1.kernel.process import ProcessTable
from l1.kernel.sync import Barrier, Mutex, Semaphore
from l1.kernel.worker_thread import ThreadPoolWorker


def _msg(name: str = "lock:reg") -> LockMessage:
    return LockMessage(op=LockOp.ACQUIRE, lock_name=name, agent_id="agent-1")


# ── sync: timed-out waiters must not linger ──


def test_mutex_timeout_removes_waiter() -> None:
    m = Mutex("mx-to-reg", timeout=0.05)
    m.acquire("agent-a")
    r = m.acquire("agent-b", blocking=True)
    assert r["success"] is False
    assert r["error"] == "timeout"
    st = m.status()
    assert st["waiter_count"] == 0
    assert st["waiters"] == []


def test_semaphore_timeout_removes_waiter(monkeypatch: pytest.MonkeyPatch) -> None:
    import l1.kernel.sync as sync_mod

    monkeypatch.setattr(sync_mod, "SEMAPHORE_DEFAULT_TIMEOUT", 0.05)
    s = Semaphore("sm-to-reg", max_count=1)
    s.acquire("agent-a")
    r = s.acquire("agent-b", blocking=True)
    assert r["success"] is False
    assert r["error"] == "timeout"
    assert s.status()["waiters"] == 0


def test_barrier_timeout_discards_arrival(monkeypatch: pytest.MonkeyPatch) -> None:
    import l1.kernel.sync as sync_mod

    monkeypatch.setattr(sync_mod, "BARRIER_DEFAULT_TIMEOUT", 0.05)
    b = Barrier("br-to-reg", count=2)
    r = b.wait("solo")
    assert r["role"] == "waiter"
    assert b._arrived == set()


def test_barrier_rounds_do_not_accumulate(monkeypatch: pytest.MonkeyPatch) -> None:
    import l1.kernel.sync as sync_mod

    monkeypatch.setattr(sync_mod, "BARRIER_DEFAULT_TIMEOUT", 0.3)
    b = Barrier("br-rounds-reg", count=2)

    def arrive(agent_id: str, results: dict) -> None:
        results[agent_id] = b.wait(agent_id)

    for prefix in ("r1", "r2"):
        results: dict = {}
        threads = [threading.Thread(target=arrive, args=(f"{prefix}-{i}", results)) for i in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2)
        assert len(results) == 2
        assert all(r["success"] for r in results.values())
    assert b._arrived == set()


# ── IPC: bounded backlog + request drain ──


def test_lockchannel_backlog_is_bounded() -> None:
    ch = LockChannel("cap-reg", max_pending=2)
    ch.send(_msg())
    ch.send(_msg())
    ch.send(_msg())
    assert ch.pending_count() == 2


def test_request_timeout_drains_message() -> None:
    ch = LockChannel("req-reg", max_pending=2)
    resp = ch.request(_msg(name="req-to"), timeout=0.05)
    assert resp == {}
    assert ch.pending_count() == 0
    assert ch._response_events == {}


# ── Process reaping releases accounting state ──


def test_reap_cleans_allocator_state() -> None:
    from l1.kernel.allocator import get_allocator, reset_allocator

    reset_allocator()
    table = ProcessTable(gc_interval=9999)
    try:
        alloc = get_allocator()
        pcb = table.spawn("doomed-agent")
        alloc.alloc("doomed-agent", "tokens", 10)
        assert table.reap(pcb.pid) is not None
        # Reap must drop accounting state — usage falls back to zeroed
        # default stats instead of the allocated "tokens": 10 snapshot.
        snapshot = alloc.usage("doomed-agent")
        assert snapshot["tokens"]["used"] == 0
        assert snapshot["tokens"]["limit"] == alloc.DEFAULTS["tokens"]
    finally:
        table._gc_running = False
        for p in list(table._processes.values()):
            if p.pid != 0:
                table.reap(p.pid)


def test_reap_cleans_limiter_state() -> None:
    from l1.kernel.resource import get_limiter, reset_limiter

    reset_limiter()
    table = ProcessTable(gc_interval=9999)
    try:
        limiter = get_limiter()
        pcb = table.spawn("doomed-limit")
        limiter.set_profile("doomed-limit", priority=1)
        table.reap(pcb.pid)
        assert "doomed-limit" not in limiter._profiles
        assert "doomed-limit" not in limiter._usage
    finally:
        table._gc_running = False
        for p in list(table._processes.values()):
            if p.pid != 0:
                table.reap(p.pid)


# ── Worker pool shrink is idempotent (no spin/thread leak) ──


def test_worker_shrink_retire_is_idempotent() -> None:
    # A large idle_timeout keeps worker threads from auto-shrinking during
    # the test — only the explicit _try_shrink calls below may retire.
    pool = ThreadPoolWorker(min_workers=2, max_workers=4, idle_timeout=3600)
    try:
        w = pool._workers[0]
        # Pool sits at its floor — shrink must refuse (steady state, no spin).
        assert pool._try_shrink(w) is False
        assert pool._try_shrink(w) is False
        # Growing above the floor enables retirement…
        pool._grow()
        g = pool._workers[-1]
        assert pool._try_shrink(g) is True  # 4 → 3
        # …and a second retire on the already-removed worker must confirm
        # the exit (idempotent guard) instead of returning False and letting
        # the thread spin on the pool forever.
        assert pool._try_shrink(g) is True  # already retired — still exit
        assert pool._try_shrink(pool._workers[-1]) is True  # 3 → 2
        # At the floor the shrink refuses instead of racing into a leak loop.
        assert pool._try_shrink(pool._workers[0]) is False
        assert len(pool._workers) == pool._min
    finally:
        pool.shutdown(wait=False)


# ── SystemBus: off() unsubscribes ──


def test_system_bus_off_unsubscribes() -> None:
    bus = SystemBus(name="reg")
    seen: list[str] = []

    def handler(evt: dict) -> None:
        seen.append(evt["event"])

    bus.on("watchdog.crash", handler)
    bus.emit("watchdog.crash")
    bus.off("watchdog.crash", handler)
    bus.emit("watchdog.crash")
    bus.emit("watchdog.crash")
    assert seen == ["watchdog.crash"]
