"""Lock port abstraction — mutual-exclusion surface decoupled from threads.

TS-friendly (P2-⑤): a future TS rewrite (single-threaded event loop or
worker pool) maps ``LockPort`` onto its own synchronization primitive
without touching callers; the current runtime uses the reentrant-thread
adapter (``ThreadLockPort``).
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any


class LockPort(ABC):
    """Mutual-exclusion surface (acquire/release + context manager)."""

    name: str = "abstract.lock"

    @abstractmethod
    def acquire(self) -> None:
        """Acquire the lock (blocking)."""

    @abstractmethod
    def release(self) -> None:
        """Release the lock."""

    def __enter__(self) -> LockPort:
        self.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


class ThreadLockPort(LockPort):
    """Reentrant-thread adapter for the current runtime."""

    name: str = "thread.lock"

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def acquire(self) -> None:
        self._lock.acquire()

    def release(self) -> None:
        self._lock.release()


def new_lock() -> LockPort:
    """Create a lock through the port surface (default: thread adapter)."""
    return ThreadLockPort()
