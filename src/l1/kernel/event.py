"""Kernel event bus — publish/subscribe with history and async dispatch."""

from __future__ import annotations

import logging
import time as _time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum, auto
from threading import RLock
from typing import Any

from .params.kernel import (
    EVENT_BUS_MAX_QUEUED,
    EVENT_BUS_SHUTDOWN_TIMEOUT,
    EVENT_BUS_WORKERS,
    EVENT_MAX_HISTORY,
    EVENT_QUERY_LIMIT,
    SIGNAL_TYPE_REGISTRY_MAX,
)

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """SignalType — enum of TASK_ASSIGN, TASK_CANCEL, REVIEW_RESULT, CONSTITUTION_UPDATE...."""

    # L3 → Agent
    TASK_ASSIGN = auto()
    TASK_CANCEL = auto()
    REVIEW_RESULT = auto()
    CONSTITUTION_UPDATE = auto()
    # Agent → L3
    TASK_DONE = auto()
    TASK_ACCEPT = auto()
    TASK_ERROR = auto()
    DISPUTE_RAISE = auto()
    AGENT_CRASH = auto()
    STATE_CHANGE = auto()
    # Agent ↔ Agent
    CROSS_REVIEW_REQ = auto()
    CROSS_REVIEW_RESP = auto()
    TERRITORY_QUERY = auto()
    # Scout
    SCOUT_DONE = auto()
    # System
    REVIEW_REQUESTED = auto()
    TOKEN_USAGE = auto()  # Token usage event (Cell/Agent → CentralCollector)
    # File change events (Sandbox → Cell/Agent)
    FILE_CHANGED = auto()  # A file was written to sandbox
    # Card / approval flow events (Card layer → EventBus → SSE/WS push)
    CARD_PENDING = auto()  # Card entered the pending queue
    APPROVAL_REQUIRED = auto()  # Card blocked by the approval gate
    APPROVAL_RESPONDED = auto()  # Approval response committed
    # NOTE: several members above (TASK_DONE, TASK_ACCEPT, TASK_ERROR,
    # AGENT_CRASH, REVIEW_RESULT, DISPUTE_RAISE, CROSS_REVIEW_REQ/RESP,
    # TERRITORY_QUERY) are reserved/tested API surface — referenced by
    # tests/l1/test_event.py as generic signals. They have no production
    # emitter today; do not delete without updating those tests.


# Extensible signal type registry — register custom signals by name
_SIGNAL_TYPE_REGISTRY: dict[str, SignalType] = {}


def register_signal_type(name: str) -> SignalType:
    """Register a custom signal type.  Returns a new SignalType member."""
    if name in _SIGNAL_TYPE_REGISTRY:
        return _SIGNAL_TYPE_REGISTRY[name]
    if hasattr(SignalType, name):
        raise ValueError(f"SignalType.{name} already exists as a built-in member")
    if len(_SIGNAL_TYPE_REGISTRY) >= SIGNAL_TYPE_REGISTRY_MAX:
        raise ValueError(f"signal type registry full ({SIGNAL_TYPE_REGISTRY_MAX} types)")
    # Dynamically extend the enum (Python 3.11+)
    count = max(m.value for m in SignalType) + 1 if SignalType.__members__ else 1
    new_member = object.__new__(SignalType)
    new_member._name_ = name
    new_member._value_ = count
    SignalType._member_map_[name] = new_member
    _SIGNAL_TYPE_REGISTRY[name] = new_member
    return new_member


def _resolve_signal_type(event_type: str) -> SignalType | None:
    """Resolve a string event type to a SignalType, or None when unavailable.

    Looks up built-in members first, then the runtime registry, then attempts
    registration. Returns None (with a warning) when the registry is full so
    callers can degrade gracefully instead of crashing on emit/subscribe.
    """
    st = _SIGNAL_TYPE_REGISTRY.get(event_type)
    if st is not None:
        return st
    builtin = getattr(SignalType, event_type, None)
    if isinstance(builtin, SignalType):
        return builtin
    try:
        return register_signal_type(event_type)
    except ValueError:
        logger.warning("signal type registry full (%d) — event type %r dropped", SIGNAL_TYPE_REGISTRY_MAX, event_type)
        return None


@dataclass
class Signal:
    """Signal — signal record (type, data, sender, target, timestamp)."""

    type: SignalType
    data: dict = field(default_factory=dict)
    sender: str = ""
    target: str = ""
    timestamp: float = field(default_factory=_time.time)

    def to_dict(self) -> dict:
        """Serialize the signal to a plain dict."""
        return {
            "type": self.type.name,
            "data": self.data,
            "sender": self.sender,
            "target": self.target,
            "timestamp": self.timestamp,
        }


class EventBus:
    """Publish/subscribe event bus with async dispatch."""

    def __init__(self, max_history: int = EVENT_MAX_HISTORY):
        self._listeners: dict[SignalType, list[Callable]] = {}
        self._history: deque[Signal] = deque(maxlen=max_history)
        self._wildcard_listeners: list[Callable] = []
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=EVENT_BUS_WORKERS, thread_name_prefix="evt")
        self._shutdown = False
        self._MAX_EVT_QUEUED = EVENT_BUS_MAX_QUEUED
        """Max pending tasks in executor queue; beyond this, new tasks are dropped."""

    def on(self, st: SignalType, cb: Callable) -> None:
        """Subscribe a callback to a signal type."""
        with self._lock:
            self._listeners.setdefault(st, []).append(cb)

    def on_any(self, cb: Callable) -> None:
        """Subscribe a callback to all signal types."""
        with self._lock:
            self._wildcard_listeners.append(cb)

    def off_any(self, cb: Callable) -> None:
        """Unsubscribe a wildcard listener previously added via on_any()."""
        with self._lock:
            if cb in self._wildcard_listeners:
                self._wildcard_listeners.remove(cb)

    def off(self, st: SignalType, cb: Callable | None = None) -> None:
        """Unsubscribe a callback, or all callbacks, for a signal type."""
        with self._lock:
            if cb:
                self._listeners[st] = [c for c in self._listeners.get(st, []) if c != cb]
            else:
                self._listeners.pop(st, None)

    def emit(self, signal: Signal) -> int:
        """Emit a signal — record to history synchronously, dispatch callbacks asynchronously.

        Returns the number of callbacks queued. Callbacks run in a thread pool so that
        a slow or blocking callback cannot block the emitter or other subscribers.
        If the bus has been shut down, callbacks are dispatched synchronously instead.
        """
        if self._shutdown:
            # Fall back to synchronous dispatch after shutdown
            with self._lock:
                self._history.append(signal)
                callbacks = list(self._listeners.get(signal.type, []))
                wildcards = list(self._wildcard_listeners)
            for cb in callbacks:
                self._safe_call(cb, signal)
            for cb in wildcards:
                self._safe_call(cb, signal)
            return len(callbacks) + len(wildcards)

        with self._lock:
            self._history.append(signal)
            callbacks = list(self._listeners.get(signal.type, []))
            wildcards = list(self._wildcard_listeners)

        count = len(callbacks) + len(wildcards)
        for cb in callbacks:
            self._bounded_submit(self._safe_call, cb, signal)
        for cb in wildcards:
            self._bounded_submit(self._safe_call, cb, signal)
        return count

    def _bounded_submit(self, fn: Callable, *args: Any) -> None:
        """Submit a task to the executor, dropping if the work queue is too deep."""
        if self._executor._work_queue.qsize() >= self._MAX_EVT_QUEUED:
            logger.warning("event_bus: executor queue full (%d), dropping task", self._MAX_EVT_QUEUED)
            return
        self._executor.submit(fn, *args)

    @staticmethod
    def _safe_call(cb: Callable, signal: Signal) -> None:
        try:
            cb(signal)
        except Exception as e:
            logger.warning("event handler: %s", e)

    # ── String-based convenience API (for extensibility, cross-platform) ──

    def emit_event(self, event_type: str, data: dict | None = None, source: str = "") -> int:
        """Emit an event by string type name.  Extensible — no enum needed."""
        st = _resolve_signal_type(event_type)
        if st is None:
            return 0  # registry full — drop the event instead of crashing
        signal = Signal(type=st, data=data or {}, sender=source)
        return self.emit(signal)

    def on_event(self, event_type: str, callback: Callable) -> None:
        """Subscribe to an event by string type name."""
        st = _resolve_signal_type(event_type)
        if st is None:
            return  # registry full — skip the subscription instead of crashing
        self.on(st, callback)

    def off_event(self, event_type: str, callback: Callable | None = None) -> None:
        """Unsubscribe from an event by string type name."""
        st = _SIGNAL_TYPE_REGISTRY.get(event_type)
        if st:
            self.off(st, callback)

    def history(self, signal_type: SignalType | None = None, limit: int = EVENT_QUERY_LIMIT) -> list[dict]:
        """Return recent emitted signals as dicts, optionally filtered by type."""
        with self._lock:
            safe_slice = list(self._history)[-limit * 2 :]
        if signal_type:
            safe_slice = [s for s in safe_slice if s.type == signal_type]
        return [s.to_dict() for s in safe_slice[-limit:]]

    def stats(self) -> dict:
        """Return event bus listener and queue counters."""
        with self._lock:
            return {
                "signal_types": len(self._listeners),
                "listeners": sum(len(v) for v in self._listeners.values()),
                "history": len(self._history),
                "wildcard_listeners": len(self._wildcard_listeners),
                "queue_depth": self._executor._work_queue.qsize(),
                "queue_max": self._MAX_EVT_QUEUED,
            }

    def shutdown(self, wait: bool = False, timeout: float | None = None) -> None:
        """Shut down the async dispatch executor. Idempotent.

        With ``wait=True``, blocks until queued tasks drain (bounded by
        *timeout*) so the executor's non-daemon threads exit — repeated
        reset_bus() calls then cannot accumulate lingering threads.
        """
        if self._shutdown:
            return
        self._shutdown = True
        # ThreadPoolExecutor.shutdown() has no timeout kwarg — stop accepting
        # new work, then join the worker threads under an explicit deadline.
        self._executor.shutdown(wait=False)
        if wait:
            deadline = None if timeout is None else _time.monotonic() + timeout
            for t in list(self._executor._threads):
                remaining = deadline - _time.monotonic() if deadline else None
                if remaining is not None and remaining <= 0:
                    break
                t.join(timeout=remaining)


_bus = EventBus()


def get_bus() -> EventBus:
    """Return the global event bus singleton."""
    return _bus


def reset_bus() -> None:
    """Reset the global event bus singleton. Used by tests."""
    global _bus
    if _bus:
        # Wait for the old executor's non-daemon threads to drain so a
        # reset does not leak threads that keep the old bus alive.
        _bus.shutdown(wait=True, timeout=EVENT_BUS_SHUTDOWN_TIMEOUT)
    _bus = EventBus()
