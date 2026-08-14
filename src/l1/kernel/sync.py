"""Sync primitives — Agent OS synchronization layer.

Mutex, Semaphore, RWLock, Barrier, Condition.
All are process-safe (cross-agent) via IPC bus.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from enum import Enum, auto
from typing import Any

from l1.kernel.ipc import LockMessage, LockOp, get_lock_bus

from .params.kernel import (
    BARRIER_DEFAULT_COUNT,
    BARRIER_DEFAULT_TIMEOUT,
    MUTEX_BOOST_THRESHOLD,
    MUTEX_CYCLE_DEBOUNCE,
    MUTEX_CYCLE_DETECT_AFTER,
    MUTEX_DEADLOCK_TIMEOUT,
    MUTEX_DEFAULT_PRIORITY,
    MUTEX_DEFAULT_TIMEOUT,
    RWLOCK_DEFAULT_TIMEOUT,
    RWLOCK_POLL_INTERVAL,
    SEMAPHORE_DEFAULT_MAX,
    SEMAPHORE_DEFAULT_TIMEOUT,
    SEMAPHORE_POLL_INTERVAL,
)
from .params.sync import MUTEX_CYCLE_MAX_DEPTH, SYNC_REGISTRY_MAX

logger = logging.getLogger(__name__)


class LockState(Enum):
    """LockState — enum of FREE, LOCKED, CONTENDED."""

    FREE = auto()
    LOCKED = auto()
    CONTENDED = auto()


class Mutex:
    """Priority-aware mutex with deadlock detection.

    Features:
      - Reentrant (same agent can lock multiple times)
      - Priority inheritance (low-priority holder gets boosted)
      - Deadlock detection (timeout + cycle detection)
      - Cross-agent (works via IPC bus, not just threads)
    """

    def __init__(
        self,
        name: str,
        timeout: float = MUTEX_DEFAULT_TIMEOUT,
        on_boost: Callable[[str, float, float], None] | None = None,
        ipc_enabled: bool = False,
    ):
        self.name = name
        self.timeout = timeout
        self.ipc_enabled = ipc_enabled
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._owner: str = ""
        self._recursion: int = 0
        self._waiters: list[tuple[str, float, float, float]] = []
        self._state = LockState.FREE
        self._effective_priority: float = MUTEX_DEFAULT_PRIORITY
        self._base_priority: float = MUTEX_DEFAULT_PRIORITY
        self._on_boost = on_boost
        self._ipc_channel = None
        if ipc_enabled:
            self._ipc_channel = get_lock_bus().get_channel(f"mutex:{name}")
            self._ipc_channel.register_handler(self._handle_ipc)

    def _detect_cycle(self, max_depth: int = MUTEX_CYCLE_MAX_DEPTH) -> list[str] | None:
        """DFS cycle detection. Returns cycle path or None.

        *max_depth* bounds traversal to prevent O(N) blowout on large _registry.

        Uses two tracking structures:
          - stack  — current DFS path for cycle detection (node in stack → cycle)
          - visited — cross-call memoization; prevents re-visiting nodes already
                      explored by a prior DFS start in the BFS queue loop.
        """
        visited: dict[str, str | None] = {}
        stack: list[str] = []
        queue = [self._owner] if self._owner else []
        for w in self._waiters:
            if w[0] not in visited:
                queue.append(w[0])

        adjacency: dict[str, list[str]] = {}
        for _mtx_name, mtx in _registry.items():
            if isinstance(mtx, Mutex) and mtx._owner:
                adjacency.setdefault(mtx._owner, [])
                for w in mtx._waiters:
                    if w[0] not in adjacency[mtx._owner]:
                        adjacency[mtx._owner].append(w[0])

        def dfs(node: str, depth: int = 0) -> list[str] | None:
            """Recursive depth-first search for a cycle from *node*; returns the cycle path or None."""
            if depth > max_depth:
                return None
            if node in stack:
                idx = stack.index(node)
                return stack[idx:] + [node]
            if node in visited:
                return None
            visited[node] = None
            stack.append(node)
            for neighbor in adjacency.get(node, []):
                result = dfs(neighbor, depth + 1)
                if result:
                    return result
            stack.pop()
            return None

        for start in queue:
            result = dfs(start)
            if result:
                return result
        return None

    def _handle_ipc(self, msg: LockMessage) -> dict | None:
        if msg.op == LockOp.ACQUIRE:
            with self._lock:
                if self._state == LockState.FREE:
                    self._state = LockState.LOCKED
                    self._owner = f"remote:{msg.agent_id}"
                    self._recursion = 1
                    return {"success": True}
            return {"success": False, "error": "contended"}
        if msg.op == LockOp.RELEASE:
            with self._lock:
                if self._owner == f"remote:{msg.agent_id}":
                    self._state = LockState.FREE
                    self._owner = ""
                    self._recursion = 0
                    return {"success": True}
            return {"success": False, "error": "not_owner"}
        if msg.op == LockOp.STATUS:
            return self.status()
        return None

    def acquire(self, agent_id: str, priority: float = MUTEX_DEFAULT_PRIORITY, blocking: bool = True) -> dict:
        """Acquire the mutex, applying priority inheritance and deadlock detection. Returns a result dict with success flag and owner."""
        deadline = time.time() + self.timeout

        with self._lock:
            if self._owner == agent_id:
                self._recursion += 1
                return {"success": True, "owner": agent_id, "recursion": self._recursion}

            if self._state == LockState.FREE:
                self._state = LockState.LOCKED
                self._owner = agent_id
                self._recursion = 1
                self._effective_priority = priority
                self._base_priority = priority
                return {"success": True, "owner": agent_id}

            if priority < self._effective_priority:
                old = self._effective_priority
                self._effective_priority = priority
                if self._on_boost:
                    self._on_boost(self._owner, old, priority)
                logger.warning(
                    "PI: %s boosted %s -> %.1f (waiter %s pri=%.1f)",
                    self.name,
                    self._owner,
                    priority,
                    agent_id,
                    priority,
                )

            if not blocking:
                return {"success": False, "error": "lock contended", "owner": self._owner}

            self._state = LockState.CONTENDED
            self._waiters.append((agent_id, priority, time.time(), 0.0))
            self._waiters.sort(key=lambda w: w[1])

        _start = time.time()
        waited = 0.0
        cycle_reported = False
        while True:
            now = time.time()
            remaining = deadline - now
            if remaining <= 0:
                break
            with self._lock:
                self._cond.wait(timeout=min(remaining, MUTEX_DEADLOCK_TIMEOUT))
            waited = time.time() - _start
            with self._lock:
                if self._state == LockState.FREE or self._owner == agent_id:
                    self._state = LockState.LOCKED
                    self._owner = agent_id
                    self._recursion = 1
                    self._effective_priority = priority
                    self._base_priority = priority
                    self._waiters = [w for w in self._waiters if w[0] != agent_id]
                    waited = round(time.time() - (deadline - self.timeout), 3)
                    return {
                        "success": True,
                        "owner": agent_id,
                        "waited": waited,
                        "boosted": waited > MUTEX_BOOST_THRESHOLD,
                    }

            if not cycle_reported and waited > MUTEX_CYCLE_DETECT_AFTER:
                # Lazify cycle detection: run at most once every 60s to avoid O(n) DFS hot path
                if not hasattr(self, "_last_cycle_check"):
                    self._last_cycle_check = 0.0
                now = time.time()
                if now - self._last_cycle_check > MUTEX_CYCLE_DEBOUNCE:
                    self._last_cycle_check = now
                    cycle = self._detect_cycle()
                    if cycle:
                        logger.critical("DEADLOCK CYCLE DETECTED: %s", " -> ".join(cycle))
                        cycle_reported = True

        # Timeout — remove our own waiting entry so repeated lock timeouts
        # cannot grow _waiters without bound (memory leak + fairness drift).
        self._drop_waiter(agent_id)
        return {
            "success": False,
            "error": "timeout",
            "owner": self._owner,
            "waited": round(waited, 3),
            "cycle_detected": cycle_reported,
        }

    def _drop_waiter(self, agent_id: str) -> bool:
        """Remove *agent_id* from ``_waiters``; returns True if an entry was dropped."""
        with self._lock:
            before = len(self._waiters)
            self._waiters = [w for w in self._waiters if w[0] != agent_id]
            return len(self._waiters) < before

    def release(self, agent_id: str) -> dict:
        """Release the mutex if *agent_id* holds it; restores base priority and wakes a waiter. Returns a result dict."""
        with self._lock:
            if self._owner != agent_id:
                return {"success": False, "error": "not the owner", "owner": self._owner}
            self._recursion -= 1
            if self._recursion > 0:
                return {"success": True, "owner": agent_id, "recursion": self._recursion}
            old = self._effective_priority
            restored = self._effective_priority != self._base_priority
            self._effective_priority = self._base_priority
            self._state = LockState.FREE
            self._owner = ""
            self._cond.notify(1)
            return {"success": True, "priority_restored": restored, "from": old, "to": self._base_priority}

    def force_unlock(self) -> dict:
        """Force-release the mutex (for test cleanup). Not for production use."""
        with self._lock:
            self._state = LockState.FREE
            self._owner = ""
            self._recursion = 0
            self._effective_priority = MUTEX_DEFAULT_PRIORITY
            self._base_priority = MUTEX_DEFAULT_PRIORITY
            self._waiters.clear()
            self._cond.notify_all()
        return {"success": True}

    def status(self) -> dict:
        """Return a snapshot dict of mutex state (owner, recursion, priorities, waiters)."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.name,
                "owner": self._owner,
                "recursion": self._recursion,
                "effective_priority": self._effective_priority,
                "base_priority": self._base_priority,
                "waiters": [(w[0], w[1]) for w in self._waiters],
                "waiter_count": len(self._waiters),
            }


class Semaphore:
    """Counting semaphore for resource limiting."""

    def __init__(self, name: str, max_count: int = SEMAPHORE_DEFAULT_MAX):
        self.name = name
        self.max_count = max_count
        self._count = max_count
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._waiters: list[str] = []

    def acquire(self, agent_id: str, blocking: bool = True) -> dict:
        """Acquire a permit if capacity remains; blocks or fails with timeout otherwise. Returns a result dict."""
        deadline = time.time() + SEMAPHORE_DEFAULT_TIMEOUT
        while True:
            with self._lock:
                if self._count > 0:
                    self._count -= 1
                    return {"success": True, "remaining": self._count}
                if not blocking:
                    return {"success": False, "error": "no capacity"}
                if agent_id not in self._waiters:
                    self._waiters.append(agent_id)
            remaining = deadline - time.time()
            if remaining <= 0:
                # Timeout — drop our waiting entry so repeated semaphore
                # timeouts cannot grow _waiters without bound.
                with self._lock:
                    if agent_id in self._waiters:
                        self._waiters.remove(agent_id)
                return {"success": False, "error": "timeout"}
            with self._lock:
                # Condition.wait must run while holding the condition lock —
                # outside it, blocking acquires crash with RuntimeError.
                self._cond.wait(timeout=min(remaining, SEMAPHORE_POLL_INTERVAL * 10))

    def release(self, agent_id: str) -> dict:
        """Return one permit to the semaphore and wake a waiting agent. Returns a result dict."""
        with self._lock:
            if self._count < self.max_count:
                self._count += 1
                if self._waiters:
                    self._waiters.pop(0)
                self._cond.notify(1)
            return {"success": True, "remaining": self._count}

    def status(self) -> dict:
        """Return a snapshot dict of semaphore state (count, max, waiters)."""
        with self._lock:
            return {"name": self.name, "count": self._count, "max": self.max_count, "waiters": len(self._waiters)}


class Barrier:
    """Barrier — wait for N agents to reach a point before proceeding."""

    def __init__(self, name: str, count: int = BARRIER_DEFAULT_COUNT):
        self.name = name
        self.count = count
        self._arrived: set[str] = set()
        self._lock = threading.Lock()
        self._event = threading.Event()

    def wait(self, agent_id: str) -> dict:
        """Mark *agent_id* as arrived; the last arriver releases all waiters. Returns a result dict with role."""
        with self._lock:
            self._arrived.add(agent_id)
            if len(self._arrived) >= self.count:
                arrived = len(self._arrived)
                self._event.set()
                # Reset the accumulator so the next barrier round starts
                # empty — otherwise _arrived grows on every round (leak).
                self._arrived.clear()
                return {"success": True, "role": "releaser", "arrived": arrived}
        waited = self._event.wait(timeout=BARRIER_DEFAULT_TIMEOUT)
        if not waited:
            # Timeout — retract this arrival so stale entries do not carry
            # into the next round.
            with self._lock:
                self._arrived.discard(agent_id)
        return {"success": True, "role": "waiter", "arrived": len(self._arrived)}

    def reset(self) -> dict:
        """Clear all arrived agents and the release event. Returns a success dict."""
        with self._lock:
            self._arrived.clear()
            self._event.clear()
        return {"success": True}


class Condition:
    """Condition variable — wait/signal/broadcast pattern.

    An agent can wait() for a condition to become true.
    Another agent can signal() or broadcast() to wake waiters.
    """

    def __init__(self, name: str):
        self.name = name
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._waiters: set[str] = set()
        self._pending_signals: int = 0

    def wait(self, agent_id: str, timeout: float = BARRIER_DEFAULT_TIMEOUT) -> dict:
        """Wait until signalled or *timeout* elapses. Returns a result dict with timed_out flag."""
        with self._lock:
            self._waiters.add(agent_id)
            if self._pending_signals > 0:
                self._pending_signals -= 1
                self._waiters.discard(agent_id)
                return {"success": True, "agent_id": agent_id, "timed_out": False}
            self._event.clear()
        ok = self._event.wait(timeout=timeout)
        with self._lock:
            self._waiters.discard(agent_id)
        return {"success": ok, "agent_id": agent_id, "timed_out": not ok}

    def signal(self, agent_id: str) -> dict:
        """Wake one waiting agent, or buffer a pending signal if none wait. Returns a success dict."""
        with self._lock:
            if self._waiters:
                self._event.set()
            else:
                self._pending_signals += 1
        return {"success": True, "signaler": agent_id, "wakeup": len(self._waiters)}

    def broadcast(self, agent_id: str) -> dict:
        """Wake all waiting agents. Returns a success dict with wakeup count."""
        self._event.set()
        return {"success": True, "signaler": agent_id, "broadcast": len(self._waiters)}

    def status(self) -> dict:
        """Return a snapshot dict of condition state (name, waiters)."""
        with self._lock:
            return {"name": self.name, "waiters": len(self._waiters)}


class RWLock:
    """Read-Write Lock — multiple readers XOR single writer."""

    def __init__(self, name: str):
        self.name = name
        # Per-agent read hold counts: reentrant reads by an already-reading
        # agent stay exempt from the writers-preference gate (no deadlock).
        self._reader_counts: dict[str, int] = {}
        self._reader_total = 0
        self._writer = ""
        self._write_waiters = 0
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)

    def read_lock(self, agent_id: str, timeout: float = RWLOCK_DEFAULT_TIMEOUT) -> dict:
        """Acquire a shared read lock, waiting while a writer holds the lock or
        writers are queued (writers-preference — prevents reader starvation of
        waiting writers). An agent already holding a read proceeds even with
        queued writers. Returns a result dict."""
        deadline = time.time() + timeout
        with self._lock:
            already_reader = self._reader_counts.get(agent_id, 0) > 0
            # Writers-preference: new readers yield to queued writers, except
            # the current write holder (writer→read reentrancy must not
            # self-deadlock against its own held write) and agents that
            # already hold a read (reentrant read).
            while (self._writer and self._writer != agent_id) or (
                self._write_waiters > 0 and not already_reader and not self._writer
            ):
                remaining = deadline - time.time()
                if remaining <= 0:
                    return {"success": False, "error": "timeout"}
                self._cond.wait(timeout=min(remaining, RWLOCK_POLL_INTERVAL))
            self._reader_counts[agent_id] = self._reader_counts.get(agent_id, 0) + 1
            self._reader_total += 1
            return {"success": True, "mode": "read", "readers": self._reader_count()}

    def write_lock(self, agent_id: str, timeout: float = RWLOCK_DEFAULT_TIMEOUT) -> dict:
        """Acquire an exclusive write lock, waiting while readers or another
        writer hold it. The waiter count is tracked under the lock (no
        unsynchronized increment). Returns a result dict."""
        deadline = time.time() + timeout
        with self._lock:
            self._write_waiters += 1
            try:
                while self._reader_count() > 0 or (self._writer and self._writer != agent_id):
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        return {"success": False, "error": "timeout"}
                    self._cond.wait(timeout=min(remaining, RWLOCK_POLL_INTERVAL))
                self._writer = agent_id
                return {"success": True, "mode": "write"}
            finally:
                self._write_waiters -= 1

    def unlock(self, agent_id: str) -> dict:
        """Release the lock held by *agent_id* (write or one read). Returns a result dict."""
        with self._lock:
            if self._writer == agent_id:
                self._writer = ""
            elif self._reader_counts.get(agent_id, 0) > 0:
                n = self._reader_counts[agent_id] - 1
                if n:
                    self._reader_counts[agent_id] = n
                else:
                    del self._reader_counts[agent_id]
                self._reader_total -= 1
            else:
                # Nothing held by this agent — report failure (aligns with Mutex).
                return {
                    "success": False,
                    "error": "not locked",
                    "writer": self._writer,
                    "readers": self._reader_count(),
                }
            self._cond.notify_all()
            return {"success": True, "mode": "write" if self._writer else "read", "readers": self._reader_count()}

    def _reader_count(self) -> int:
        """Total number of held read locks across all agents (O(1) running total)."""
        return self._reader_total

    def status(self) -> dict:
        """Return a snapshot dict of RWLock state (readers, writer, write_waiters)."""
        with self._lock:
            return {
                "name": self.name,
                "readers": self._reader_count(),
                "writer": self._writer,
                "write_waiters": self._write_waiters,
            }


# ── Global registry (thread-safe) ──

_registry: dict[str, Any] = {}
_registry_lock = threading.Lock()


def _registry_free(obj: Any) -> bool:
    """True if a sync object is uncontended (safe to evict from the registry)."""
    try:
        st = obj.status()
    except Exception:
        return False
    if st.get("state") == "CONTENDED":
        return False
    if st.get("owner") or st.get("writer"):
        return False
    return not (st.get("waiters") or st.get("waiter_count") or st.get("write_waiters") or st.get("readers"))


def _evict_oldest_free_locked() -> bool:
    """Evict the oldest uncontended entry to bound registry growth.

    Caller must hold ``_registry_lock``. Only entries whose object is
    currently free are removed — an in-use lock is never dropped from the
    lookup table (that would silently break a later get_*() caller, which
    would then receive a second object for the same name). Returns True if
    an entry was evicted, False if every entry is contended.
    """
    for reg_name, obj in list(_registry.items()):
        if _registry_free(obj):
            _registry.pop(reg_name, None)
            return True
    return False


def _get_or_create(name: str, factory) -> Any:
    with _registry_lock:
        obj = _registry.get(name)
        if obj is not None:
            return obj
        if len(_registry) >= SYNC_REGISTRY_MAX and not _evict_oldest_free_locked():
            # Hard bound: never grow past SYNC_REGISTRY_MAX. Degrade to a
            # standalone (unregistered) object so callers keep working and
            # the registry cannot leak memory. Dedup is lost only in this
            # saturated edge case (256+ simultaneously in-use named locks).
            logger.warning("sync registry saturated (%d) — returning unregistered %r", SYNC_REGISTRY_MAX, name)
            return factory()
        obj = factory()
        _registry[name] = obj
        return obj


def unregister(name: str) -> bool:
    """Remove a named sync object from the registry (memory hygiene).

    Returns True if the object existed and was removed. No-op for unknown
    names. Explicit callers should unregister long-lived named locks when
    they are no longer needed so the registry stays bounded.
    """
    with _registry_lock:
        return _registry.pop(name, None) is not None


def get_mutex(name: str, timeout: float = MUTEX_DEFAULT_TIMEOUT, ipc_enabled: bool = False) -> Mutex:
    """Return the named Mutex, creating it on first use."""
    return _get_or_create(name, lambda: Mutex(name, timeout, ipc_enabled=ipc_enabled))


def get_semaphore(name: str, max_count: int = SEMAPHORE_DEFAULT_MAX) -> Semaphore:
    """Return the named Semaphore, creating it on first use."""
    return _get_or_create(name, lambda: Semaphore(name, max_count))


def get_barrier(name: str, count: int = BARRIER_DEFAULT_COUNT) -> Barrier:
    """Return the named Barrier, creating it on first use."""
    return _get_or_create(name, lambda: Barrier(name, count))


def get_rwlock(name: str) -> RWLock:
    """Return the named RWLock, creating it on first use."""
    return _get_or_create(name, lambda: RWLock(name))


def get_condition(name: str) -> Condition:
    """Return the named Condition, creating it on first use."""
    return _get_or_create(name, lambda: Condition(name))


def reset_registry() -> None:
    """Clear the global sync-object registry (for tests / hot reset)."""
    with _registry_lock:
        _registry.clear()


def registry_status() -> dict:
    """Return status snapshots for every registered sync object."""
    with _registry_lock:
        return {name: obj.status() for name, obj in list(_registry.items())}
