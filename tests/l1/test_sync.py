"""Tests for sync primitives — Mutex, Semaphore, Barrier, Condition, RWLock."""

from __future__ import annotations

from l1.kernel.sync import (
    Barrier,
    Condition,
    Mutex,
    RWLock,
    Semaphore,
    get_barrier,
    get_condition,
    get_mutex,
    get_rwlock,
    get_semaphore,
    registry_status,
    reset_registry,
)

# ── Mutex ──


def test_mutex_acquire_release() -> None:
    m = Mutex("mx1")
    r = m.acquire("agent-1")
    assert r["success"] is True
    r = m.release("agent-1")
    assert r["success"] is True


def test_mutex_status_shows_owner() -> None:
    m = Mutex("mx2")
    m.acquire("agent-a")
    s = m.status()
    assert s["owner"] == "agent-a"
    assert s["state"] == "LOCKED"


def test_mutex_double_acquire_same_agent_reentrant() -> None:
    m = Mutex("mx3")
    m.acquire("agent-x")
    r = m.acquire("agent-x")  # reentrant
    assert r["success"] is True


def test_mutex_force_unlock() -> None:
    m = Mutex("mx4")
    m.acquire("agent-a")
    r = m.force_unlock()
    assert r["success"] is True
    # Mutex should be free after force unlock
    s = m.status()
    assert s["state"] == "FREE"


def test_mutex_release_not_owner_fails() -> None:
    m = Mutex("mx5")
    m.acquire("owner")
    r = m.release("intruder")
    assert r["success"] is False


def test_mutex_status_free() -> None:
    m = Mutex("mx6")
    s = m.status()
    assert s["state"] == "FREE"


# ── Semaphore ──


def test_semaphore_acquire_release() -> None:
    s = Semaphore("sm1", max_count=2)
    r = s.acquire("agent-1")
    assert r["success"] is True
    r = s.release("agent-1")
    assert r["success"] is True


def test_semaphore_release_frees_slot() -> None:
    s = Semaphore("sm2", max_count=1)
    s.acquire("agent-a")
    s.release("agent-a")
    r = s.acquire("agent-b")
    assert r["success"] is True


def test_semaphore_status() -> None:
    s = Semaphore("sm3", max_count=3)
    s.acquire("agent-a")
    st = s.status()
    assert st["count"] == 2  # count starts at max_count (3), decrements on acquire
    assert st["max"] == 3


# ── Barrier ──


def test_barrier_wait_reset() -> None:
    import threading

    b = Barrier("br1", count=3)

    def arrive(results: dict[str, dict], agent_id: str) -> None:
        results[agent_id] = b.wait(agent_id)

    def run_all(prefix: str) -> dict[str, dict]:
        results: dict[str, dict] = {}
        threads = [threading.Thread(target=arrive, args=(results, f"{prefix}-{i}")) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2)
        return results

    first = run_all("agent")
    # All three agents reached the barrier → released without blocking.
    assert len(first) == 3
    assert all(r["success"] is True for r in first.values())
    assert {r["role"] for r in first.values()} == {"releaser", "waiter"}
    r = b.reset()
    assert r["success"] is True
    # After reset the barrier must be usable again — all three re-arrive.
    second = run_all("again")
    assert len(second) == 3
    assert all(r["success"] is True for r in second.values())


# ── Condition ──


def test_condition_wait_signal() -> None:
    c = Condition("cv1")
    r = c.wait("agent-1", timeout=0.1)
    # Timeout expected — no signal was sent
    assert r["success"] is False
    assert r["timed_out"] is True


def test_condition_signal_no_waiter() -> None:
    c = Condition("cv2")
    r = c.signal("agent-1")
    assert r["success"] is True
    assert r["wakeup"] == 0


def test_condition_broadcast() -> None:
    c = Condition("cv3")
    r = c.broadcast("agent-1")
    assert r["success"] is True


def test_condition_status() -> None:
    c = Condition("cv4")
    s = c.status()
    assert "waiters" in s


# ── RWLock ──


def test_rwlock_read_lock_multiple() -> None:
    rw = RWLock("rw1")
    r1 = rw.read_lock("agent-a")
    assert r1["success"] is True
    r2 = rw.read_lock("agent-b")
    assert r2["success"] is True
    rw.unlock("agent-a")
    rw.unlock("agent-b")


def test_rwlock_write_lock_exclusive() -> None:
    rw = RWLock("rw2")
    r = rw.write_lock("agent-a")
    assert r["success"] is True
    rw.unlock("agent-a")


def test_rwlock_write_blocked_by_readers() -> None:
    rw = RWLock("rw3")
    rw.read_lock("reader1")
    # immediate non-blocking write attempt should fail with readers active
    r = rw.write_lock("writer", timeout=0.01)
    assert r["success"] is False or r.get("timeout", False)
    rw.unlock("reader1")


def test_rwlock_unlock_without_lock_returns_error() -> None:
    rw = RWLock("rw4")
    r = rw.unlock("nobody")
    assert r["success"] is False


def test_rwlock_status() -> None:
    rw = RWLock("rw5")
    rw.read_lock("agent-r")
    s = rw.status()
    assert s.get("readers", 0) >= 1


def test_rwlock_writer_queued_blocks_new_readers() -> None:
    """Writers-preference: once a writer queues, new readers must wait so a
    sustained reader stream cannot starve it (the P2 fairness fix)."""
    import threading
    import time

    rw = RWLock("rw-pref1")
    rw.read_lock("reader-a")
    result: dict = {}

    def _writer() -> None:
        result["w"] = rw.write_lock("writer", timeout=5.0)

    t = threading.Thread(target=_writer)
    t.start()
    deadline = time.time() + 10.0
    while rw.status().get("write_waiters", 0) < 1 and time.time() < deadline:
        time.sleep(0.01)
    assert rw.status()["write_waiters"] >= 1
    # A new reader barging in while the writer is queued must be refused.
    r = rw.read_lock("reader-b", timeout=0.05)
    assert r["success"] is False
    rw.unlock("reader-a")  # readers leave → queued writer proceeds
    t.join(timeout=10)
    assert result["w"]["success"] is True
    assert rw.status()["writer"] == "writer"
    rw.unlock("writer")


def test_rwlock_reentrant_reader_exempt_from_writer_queue() -> None:
    """An agent already holding a read proceeds even with queued writers —
    otherwise reentrant reads would deadlock against the preference gate."""
    import threading
    import time

    rw = RWLock("rw-pref2")
    rw.read_lock("reader-a")
    result: dict = {}

    def _writer() -> None:
        result["w"] = rw.write_lock("writer", timeout=5.0)

    t = threading.Thread(target=_writer)
    t.start()
    deadline = time.time() + 10.0
    while rw.status().get("write_waiters", 0) < 1 and time.time() < deadline:
        time.sleep(0.01)
    assert rw.status()["write_waiters"] >= 1
    r = rw.read_lock("reader-a", timeout=0.05)
    assert r["success"] is True  # same-agent reentrant read is exempt
    rw.unlock("reader-a")  # first hold
    rw.unlock("reader-a")  # second (reentrant) hold
    t.join(timeout=10)
    assert result["w"]["success"] is True
    rw.unlock("writer")


def test_rwlock_write_waiters_returns_to_zero_on_timeout() -> None:
    """A timed-out writer must not leave a stale waiter count behind."""
    rw = RWLock("rw-pref3")
    rw.read_lock("reader-a")
    r = rw.write_lock("writer", timeout=0.01)
    assert r["success"] is False
    assert rw.status()["write_waiters"] == 0
    rw.unlock("reader-a")


# ── Global singleton getters ──


def test_get_mutex() -> None:
    m = get_mutex("global-mx")
    assert m is not None
    assert m.name == "global-mx"


def test_get_semaphore() -> None:
    s = get_semaphore("global-sm")
    assert s is not None


def test_get_barrier() -> None:
    b = get_barrier("global-br", count=2)
    assert b is not None


def test_get_rwlock() -> None:
    rw = get_rwlock("global-rw")
    assert rw is not None


def test_get_condition() -> None:
    c = get_condition("global-cv")
    assert c is not None


def test_registry_status() -> None:
    # Ensure a few primitives exist in registry
    get_mutex("reg-mx")
    get_semaphore("reg-sm")
    s = registry_status()
    assert "reg-mx" in s
    assert "reg-sm" in s


def test_unregister_removes_entry() -> None:
    from l1.kernel.sync import unregister

    get_mutex("unreg-mx")
    assert "unreg-mx" in registry_status()
    assert unregister("unreg-mx") is True
    assert "unreg-mx" not in registry_status()
    assert unregister("unreg-mx") is False  # idempotent no-op


def test_registry_capped_evicts_free_entry(monkeypatch) -> None:
    """Past SYNC_REGISTRY_MAX, an uncontended entry is evicted to bound memory."""
    import l1.kernel.sync as sync_mod

    monkeypatch.setattr(sync_mod, "SYNC_REGISTRY_MAX", 2)
    reset_registry()
    get_mutex("cap-a")
    get_mutex("cap-b")
    # cap-a/cap-b are free; a third creation must evict one of them
    get_mutex("cap-c")
    names = set(registry_status())
    assert "cap-c" in names
    assert len(names) <= 2


def test_registry_saturated_does_not_grow(monkeypatch) -> None:
    """All entries contended: a new name must NOT grow the registry past the cap."""
    import l1.kernel.sync as sync_mod

    monkeypatch.setattr(sync_mod, "SYNC_REGISTRY_MAX", 2)
    reset_registry()
    m1 = get_mutex("busy-a")
    m2 = get_mutex("busy-b")
    # Acquire both so no free entry exists to evict
    assert m1.acquire("owner-a")["success"]
    assert m2.acquire("owner-b")["success"]
    m3 = get_mutex("busy-c")  # saturated — must degrade, not grow
    assert m3 is not None
    names = set(registry_status())
    assert len(names) == 2  # hard bound holds
    assert "busy-c" not in names  # returned unregistered standalone
    reset_registry()
