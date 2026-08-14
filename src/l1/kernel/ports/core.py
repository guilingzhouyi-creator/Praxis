"""Core port abstractions — transport, channel, event bus, worker pool."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from .types import Event, Result


class TransportPort(ABC):
    """Transmit bytes to remote endpoints; receive messages via handler callback."""

    name: str = "abstract.transport"

    @abstractmethod
    def start(self, node_id: str, config: Any) -> Result: ...
    @abstractmethod
    def stop(self) -> Result: ...
    @abstractmethod
    def send(self, target: Any, data: bytes) -> Result: ...
    @abstractmethod
    def register_handler(self, msg_type: str, handler: Callable) -> None: ...


class ChannelPort(ABC):
    """Message channel — decouples producer from consumer, with backpressure."""

    @abstractmethod
    def put(self, item: Any, timeout: float | None = None) -> bool: ...
    @abstractmethod
    def get(self, timeout: float | None = None) -> Any | None: ...
    @abstractmethod
    def size(self) -> int: ...
    @abstractmethod
    def capacity(self) -> int: ...
    @abstractmethod
    def close(self) -> None: ...


class EventBusPort(ABC):
    """Publish/subscribe event bus — decouples event producers from consumers."""

    @abstractmethod
    def emit(self, event: Event) -> None: ...
    @abstractmethod
    def subscribe(self, handler: Callable | None = None, pattern: str | None = None) -> str: ...
    @abstractmethod
    def unsubscribe(self, sub_id: str) -> bool: ...
    @abstractmethod
    def stats(self) -> dict: ...


class WorkerPort(ABC):
    """Abstract concurrency executor — decouples task submission from execution."""

    @abstractmethod
    def submit(self, fn: Callable, *args: Any, **kwargs: Any) -> Result: ...
    @abstractmethod
    def shutdown(self, wait: bool = True, timeout: float | None = None) -> Result: ...
    @abstractmethod
    def stats(self) -> dict: ...
