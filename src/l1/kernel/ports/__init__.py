"""Ports — pure abstract interfaces for hexagonal architecture.

Split into sub-modules for maintainability:
  types.py     — Endpoint, Result, Message, Event
  core.py      — TransportPort, ChannelPort, EventBusPort, WorkerPort
  service.py   — I18nPort, CardRegistryPort, MonitorBusPort, LLMPort,
                 AuthPort, WebSocketPort, RpcServerPort, FilesystemPort
  registry.py  — register_port, get_port, reset_ports

All public names are re-exported here so existing
``from l1.kernel.ports import X`` imports keep working.
"""

from l1.kernel.ports.core import (
    ChannelPort,
    EventBusPort,
    TransportPort,
    WorkerPort,
)
from l1.kernel.ports.registry import (
    _PORTS,
    get_port,
    register_port,
    reset_ports,
)
from l1.kernel.ports.service import (
    AuthPort,
    CardRegistryPort,
    FilesystemPort,
    I18nPort,
    LLMConfig,
    LLMPort,
    MonitorBusPort,
    RpcServerPort,
    WebSocketPort,
)
from l1.kernel.ports.types import (
    Endpoint,
    Event,
    Message,
    Result,
)

__all__ = [
    "AuthPort",
    "CardRegistryPort",
    "ChannelPort",
    "Endpoint",
    "Event",
    "EventBusPort",
    "FilesystemPort",
    "I18nPort",
    "LLMConfig",
    "LLMPort",
    "Message",
    "MonitorBusPort",
    "Result",
    "RpcServerPort",
    "TransportPort",
    "WebSocketPort",
    "WorkerPort",
    "_PORTS",
    "get_port",
    "register_port",
    "reset_ports",
]
