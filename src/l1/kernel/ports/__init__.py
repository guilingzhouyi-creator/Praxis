"""Ports — pure abstract interfaces for hexagonal architecture.

Split into sub-modules for maintainability:
  types.py     — Endpoint, Result, Message, Event
  core.py      — TransportPort, ChannelPort, EventBusPort, WorkerPort, TaskHandle
  service.py   — AuthPort, WebSocketPort, RpcServerPort, FilesystemPort,
                 InputActivityPort (domain ports live in l3.ports / l4.ports)
  storage.py   — StoragePort, FsStoragePort (TS-friendly read/write surface)
  lock.py      — LockPort, ThreadLockPort (mutex abstraction)
  process.py   — ProcessPort, SubprocessProcessPort, ProcessResult (exec seam)
  scheduler.py — KernelSchedulerPort (submit/poll/preempt mechanism seam)
  registry.py  — register_port, get_port, reset_ports

All public names are re-exported here so existing
``from l1.kernel.ports import X`` imports keep working.
"""

from l1.kernel.ports.core import (
    ChannelPort,
    EventBusPort,
    TaskHandle,
    TransportPort,
    WorkerPort,
)
from l1.kernel.ports.lock import LockPort, ThreadLockPort, new_lock
from l1.kernel.ports.process import (
    ProcessOptions,
    ProcessPort,
    ProcessResult,
    SubprocessProcessPort,
    get_process_port,
)
from l1.kernel.ports.registry import (
    _PORTS,
    get_port,
    register_port,
    reset_ports,
)
from l1.kernel.ports.scheduler import KernelSchedulerPort
from l1.kernel.ports.service import (
    AuthPort,
    FilesystemPort,
    InputActivityPort,
    RpcServerPort,
    WebSocketPort,
)
from l1.kernel.ports.storage import (
    FsStoragePort,
    StoragePort,
    get_storage,
    reset_storage,
    set_storage,
)
from l1.kernel.ports.types import (
    CandidateBinding,
    CandidateCollectionResult,
    CandidateEvidence,
    CandidateRecord,
    CandidateResult,
    CandidateSnapshot,
    CandidateState,
    CandidateStatus,
    CandidateValidation,
    Endpoint,
    Event,
    InputActivitySnapshot,
    Message,
    Result,
)

__all__ = [
    "AuthPort",
    "CandidateBinding",
    "CandidateCollectionResult",
    "CandidateEvidence",
    "CandidateResult",
    "CandidateRecord",
    "CandidateSnapshot",
    "CandidateState",
    "CandidateStatus",
    "CandidateValidation",
    "ChannelPort",
    "Endpoint",
    "Event",
    "EventBusPort",
    "FilesystemPort",
    "FsStoragePort",
    "InputActivityPort",
    "InputActivitySnapshot",
    "KernelSchedulerPort",
    "LockPort",
    "Message",
    "ProcessPort",
    "ProcessOptions",
    "ProcessResult",
    "Result",
    "RpcServerPort",
    "StoragePort",
    "SubprocessProcessPort",
    "TaskHandle",
    "ThreadLockPort",
    "TransportPort",
    "WebSocketPort",
    "WorkerPort",
    "_PORTS",
    "get_port",
    "get_process_port",
    "get_storage",
    "new_lock",
    "register_port",
    "reset_ports",
    "reset_storage",
    "set_storage",
]
