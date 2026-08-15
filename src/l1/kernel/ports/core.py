"""Core port abstractions — transport, channel, event bus, worker pool."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from .types import Event, Result


class TaskHandle:
    """Future-like handle for a task submitted through ``WorkerPort.submit_result``.

    Carries the task's return value (or exception) across the worker boundary so
    a caller can await a computed result — the missing half of the fire-and-forget
    ``submit()`` contract. Built on ``threading.Event`` in the stdlib adapter; a
    Rust worker maps it onto its own completion primitive without changing callers.
    """

    def __init__(self) -> None:
        self._done = threading.Event()
        self._result: Any = None
        self._exc: BaseException | None = None

    def set_result(self, value: Any) -> None:
        """Record a successful result and signal completion."""
        self._result = value
        self._done.set()

    def set_exception(self, exc: BaseException) -> None:
        """Record a task exception and signal completion."""
        self._exc = exc
        self._done.set()

    def done(self) -> bool:
        """Whether the task has completed (successfully or with an exception)."""
        return self._done.is_set()

    def exception(self, timeout: float | None = None) -> BaseException | None:
        """Block until done (bounded by *timeout*); return the task exception or None."""
        if not self._done.wait(timeout):
            raise TimeoutError("task did not complete within timeout")
        return self._exc

    def result(self, timeout: float | None = None) -> Any:
        """Block until done (bounded by *timeout*); return the value or re-raise."""
        if not self._done.wait(timeout):
            raise TimeoutError("task did not complete within timeout")
        if self._exc is not None:
            raise self._exc
        return self._result


class TransportPort(ABC):
    """Transmit bytes to remote endpoints; receive messages via handler callback."""

    name: str = "abstract.transport"

    @abstractmethod
    def start(self, node_id: str, config: Any) -> Result:
        """Start the transport bound to *node_id* with the given config."""

    @abstractmethod
    def stop(self) -> Result:
        """Stop the transport and release its resources."""

    @abstractmethod
    def send(self, target: Any, data: bytes) -> Result:
        """Send raw *data* bytes to the remote *target* endpoint."""

    @abstractmethod
    def register_handler(self, msg_type: str, handler: Callable) -> None:
        """Register a callback for incoming messages of *msg_type*."""


class ChannelPort(ABC):
    """Message channel — decouples producer from consumer, with backpressure."""

    @abstractmethod
    def put(self, item: Any, timeout: float | None = None) -> bool:
        """Enqueue *item*; return False when the timeout expires or channel closes."""

    @abstractmethod
    def get(self, timeout: float | None = None) -> Any | None:
        """Dequeue the next item; return None on timeout or when closed."""

    @abstractmethod
    def size(self) -> int:
        """Number of items currently queued."""

    @abstractmethod
    def capacity(self) -> int:
        """Maximum number of items the channel can hold."""

    @abstractmethod
    def close(self) -> None:
        """Close the channel; blocked producers/consumers unblock."""


class EventBusPort(ABC):
    """Publish/subscribe event bus — decouples event producers from consumers."""

    @abstractmethod
    def emit(self, event: Event) -> None:
        """Publish *event* to all matching subscribers."""

    @abstractmethod
    def subscribe(self, handler: Callable | None = None, pattern: str | None = None) -> str:
        """Subscribe *handler* (optionally filtered by *pattern*); return a sub id."""

    @abstractmethod
    def unsubscribe(self, sub_id: str) -> bool:
        """Remove a subscription by id; return whether it existed."""

    @abstractmethod
    def stats(self) -> dict:
        """Return bus statistics (subscriber count, emitted events)."""


class WorkerPort(ABC):
    """Abstract concurrency executor — decouples task submission from execution."""

    @abstractmethod
    def submit(self, fn: Callable, *args: Any, **kwargs: Any) -> Result:
        """Schedule *fn* for execution; return a Result (fire-and-forget)."""

    @abstractmethod
    def shutdown(self, wait: bool = True, timeout: float | None = None) -> Result:
        """Stop accepting work and drain/stop workers; return a Result."""

    @abstractmethod
    def stats(self) -> dict:
        """Return worker-pool statistics (pending, running, completed)."""

    def submit_result(self, fn: Callable, *args: Any, **kwargs: Any) -> TaskHandle:
        """Submit a task and return a TaskHandle for its result/exception.

        Non-abstract so existing WorkerPort adapters keep working unchanged;
        adapters that support result retrieval (e.g. ThreadPoolWorker) override
        it. The default signals that this adapter is fire-and-forget only.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support submit_result()")
