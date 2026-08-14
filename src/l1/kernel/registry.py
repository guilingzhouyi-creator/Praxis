"""Central system registry — single source of truth for kernel state.

Queries:
  registry.modules()    → all 17 kernel modules + status
  registry.devices()    → all registered devices
  registry.processes()  → process table
  registry.interrupts() → interrupt counts
  registry.audit()      → recent audit log
  registry.syscall()    → syscall dispatch table
  registry.settings()   → all system settings
  registry.summary()    → unified system overview
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .params.kernel import REGISTRY_QUERY_LIMIT, GateStatus

logger = logging.getLogger(__name__)


class Registry:
    """Queries all kernel subsystems and aggregates their state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sections: dict[str, Any] = {}

    def modules(self) -> dict[str, Any]:
        """Return the health status of all kernel modules."""
        from .__init__ import health as _health_fn

        return _health_fn().get("modules", {})

    def devices(self) -> list[dict]:
        """Return all registered devices."""
        from .device import get_device_manager

        return get_device_manager().list()

    def processes(self) -> list[dict]:
        """Return the current process table."""
        from .process import get_table

        return get_table().list_processes()

    def interrupts(self) -> dict[str, Any]:
        """Return interrupt counts and recent interrupt records."""
        from .interrupt import get_table

        t = get_table()
        return {"counts": t.counts(), "recent": t.recent(10)}

    def audit(self, limit: int = REGISTRY_QUERY_LIMIT) -> list[dict]:
        """Return the recent audit log, up to *limit* entries."""
        from . import get_audit_log

        return get_audit_log(limit=limit)

    def tool_chains(self) -> dict[str, Any]:
        """Return tool-chain statistics and recent executions."""
        from .tool_chain import get_tool_chain

        c = get_tool_chain()
        return {"stats": c.stats(), "recent": c.recent(10)}

    def settings(self) -> dict[str, Any]:
        """Return all system settings."""
        from .settings import get_settings

        return get_settings().all()

    def syscalls(self) -> list[str]:
        """Return the sorted list of known syscall names (builtin + custom)."""
        from . import _SYSCALL_REGISTRY

        base = [
            "mutex.acquire",
            "mutex.release",
            "mutex.status",
            "semaphore.acquire",
            "semaphore.release",
            "semaphore.status",
            "barrier.wait",
            "barrier.reset",
            "condition.wait",
            "condition.signal",
            "condition.broadcast",
            "signal.emit",
            "signal.on",
            "signal.off",
            "resource.check",
            "resource.release",
            "resource.usage",
            "process.spawn",
            "process.exit",
            "process.list",
            "alloc.alloc",
            "alloc.free",
            "alloc.usage",
        ]
        custom = list(_SYSCALL_REGISTRY.keys())
        return sorted(base + custom)

    # ── Generic section store (register-backed state, e.g. TODO table) ──

    def set_section(self, name: str, data: Any) -> None:
        """Store a named state section (register-backed, e.g. ``todo_table``).

        Layer-safe: L1 only stores opaque data; producers (L3 services like
        TodoTracker) write snapshots here and consumers read them back
        without cross-layer imports.
        """
        with self._lock:
            self._sections[name] = data

    def get_section(self, name: str, default: Any = None) -> Any:
        """Read a named state section previously written by set_section."""
        with self._lock:
            return self._sections.get(name, default)

    def clear_section(self, name: str) -> None:
        """Drop a named state section (used by tests / lifecycle)."""
        with self._lock:
            self._sections.pop(name, None)

    def todo_table(self) -> dict:
        """Return the register-backed TODO table snapshot (default empty)."""
        return self.get_section("todo_table", {"status": "open", "iteration": 0, "tasks": []})

    def summary(self) -> dict[str, Any]:
        """Return a unified system overview (modules, processes, devices, syscalls)."""
        m = self.modules()
        healthy = sum(1 for v in m.values() if v.get("status") == GateStatus.PASS)
        return {
            "modules": {"total": len(m), "healthy": healthy},
            "processes": len(self.processes()),
            "devices": len(self.devices()),
            "syscalls": len(self.syscalls()),
            "timestamp": time.time(),
        }


_registry: Registry | None = None
_registry_lock = threading.Lock()


def get_registry() -> Registry:
    """Get the system registry singleton (lazily created)."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = Registry()
    return _registry
