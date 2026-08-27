"""ErrorBus core — unified error log bus implementation.

Extracted from ``error_bus/__init__.py`` (large __init__ anti-pattern).
Owns ``ErrorBus`` (ingestion/dedup/query/SSE) and the global singleton;
the trace-id context lives in ``trace.py``, the entry model in ``entry.py``
and the capture facade in ``capture.py`` — all re-exported here so
``from l3.error_bus.core import capture`` keeps working.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from l1.kernel.params.system import (
    ERROR_BUS_BUFFER,
    ERROR_BUS_QUERY_LIMIT,
    ERROR_BUS_TOP_SOURCES,
    ERROR_EXPORT_FILE,
    LOG_ROTATE_GLOB,
    LOG_TRUNC_200,
)
from l1.kernel.paths import get_paths as _gp
from l3._base import BaseService

from .capture import capture, capture_exception, error_boundary  # noqa: F401 — re-export
from .entry import ErrorLogEntry, _caller_source, _compute_fingerprint, _format_exc  # noqa: F401 — re-export
from .trace import get_trace_id, propagate_context, set_trace_id, trace_scope  # noqa: F401 — re-export

logger = logging.getLogger(__name__)

_LOG_DIR = Path(_gp().config_dir) / "logs"


# ══════════════════════════════════════════════════════════════════════
# ErrorBus — Merging engine
# ══════════════════════════════════════════════════════════════════════


class ErrorBus(BaseService):
    """Unified error log bus — ingestion, deduplication, query, SSE.

    Responsibilities:
      1. ingest() receives errors from all sources → dedup → write to LogService + EventBus
      2. Maintains a ring buffer for fast queries
      3. Exposes REST API query/statistics interfaces
    """

    def __init__(self, max_entries: int = ERROR_BUS_BUFFER):
        super().__init__("error_bus")
        self._max_entries = max_entries
        self._buffer: deque[ErrorLogEntry] = deque(maxlen=max_entries)
        self._fingerprint_index: dict[str, ErrorLogEntry] = {}
        self._lock = threading.RLock()

        # SSE clients
        self._sse_clients: list[queue.Queue] = []
        self._sse_lock = threading.RLock()

        # Stats cache
        self._stats_cache: dict = {}
        self._stats_ts: float = 0.0

    # ── Lifecycle ──

    def _on_start(self) -> dict:
        """Subscribe to EventBus error events on startup"""
        try:
            from l1.kernel import get_event_bus

            bus = get_event_bus()
            bus.on_event("error_log", self._on_error_event)
        except Exception as e:
            logger.warning("error_bus: event bus subscribe failed: %s", e)
        logger.info("error_bus started (max_entries=%d)", self._max_entries)
        return {"success": True, "max_entries": self._max_entries}

    def _on_stop(self) -> dict:
        # Close all SSE connections
        with self._sse_lock:
            for q in self._sse_clients:
                q.put(None)  # Sentinel to notify disconnection
            self._sse_clients.clear()
        return {"success": True}

    # ── Ingestion entry points ──

    def error(
        self,
        message: str,
        error_code: str = "E_INTERNAL",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        stack_trace: str = "",
        agent_id: str = "",
        task_id: str = "",
        trace_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """Log an ERROR level error."""
        return self._ingest(
            level="ERROR",
            message=message,
            error_code=error_code,
            component=component,
            service=service or component,
            source=source,
            stack_trace=stack_trace,
            agent_id=agent_id,
            task_id=task_id,
            context=context or {},
        )

    def critical(
        self,
        message: str,
        error_code: str = "E_INTERNAL",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        stack_trace: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """Log a CRITICAL level error."""
        return self._ingest(
            level="CRITICAL",
            message=message,
            error_code=error_code,
            component=component,
            service=service or component,
            source=source,
            stack_trace=stack_trace,
            agent_id=agent_id,
            task_id=task_id,
            context=context or {},
        )

    def warn(
        self,
        message: str,
        error_code: str = "",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """Log a WARN level warning."""
        return self._ingest(
            level="WARN",
            message=message,
            error_code=error_code or "E_WARN",
            component=component,
            service=service or component,
            source=source,
            agent_id=agent_id,
            task_id=task_id,
            context=context or {},
        )

    def exception(
        self,
        exc: Exception,
        message: str = "",
        error_code: str = "E_INTERNAL",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """Extract information from an Exception object and log it.

        Automatically extracts stack_trace; if source is empty, auto-infers the call location.
        """
        stack_trace = _format_exc(exc)
        _source = source or _caller_source(depth=3)
        _message = message or str(exc)[:LOG_TRUNC_200]
        return self.error(
            message=_message,
            error_code=error_code,
            component=component,
            service=service,
            source=_source,
            stack_trace=stack_trace,
            agent_id=agent_id,
            task_id=task_id,
            context=context or {},
        )

    # ── Internal ingestion logic ──

    def _ingest(
        self,
        level: str,
        message: str,
        error_code: str,
        component: str,
        service: str,
        source: str,
        stack_trace: str = "",
        agent_id: str = "",
        task_id: str = "",
        trace_id: str = "",
        context: dict | None = None,
    ) -> dict:
        entry = ErrorLogEntry(
            level=level,
            service=service,
            message=message,
            timestamp=time.time(),
            agent_id=agent_id,
            task_id=task_id,
            trace_id=trace_id or get_trace_id(),
            error_code=error_code,
            component=component,
            source=source,
            stack_trace=stack_trace,
            context=context or {},
        )

        with self._lock:
            # Deduplication
            existing = self._fingerprint_index.get(entry.fingerprint)
            if existing:
                existing.count += 1
                existing.timestamp = entry.timestamp  # Update timestamp
                result_entry = existing
            else:
                # deque(maxlen=N) auto-evicts the leftmost element on append when full;
                # must capture the entry about to be evicted before appending, and
                # after appending clean up its fingerprint index to keep
                # the index in sync with the actual buffer contents.
                evicted: ErrorLogEntry | None = None
                if len(self._buffer) >= self._max_entries:
                    evicted = self._buffer[0]
                self._buffer.append(entry)
                self._fingerprint_index[entry.fingerprint] = entry
                result_entry = entry
                if evicted is not None and evicted.fingerprint in self._fingerprint_index:
                    del self._fingerprint_index[evicted.fingerprint]

        # ── Push to LogService ──
        try:
            from l3.bus.log import get_service as get_log_service

            log_svc = get_log_service()
            log_svc.log(
                level=level,
                message=f"[{error_code}] {message[:LOG_TRUNC_200]}",
                service=service,
                agent_id=agent_id,
                task_id=task_id,
            )
        except Exception as e:
            logger.warning("error_bus: log push failed: %s", e)

        # ── Push to EventBus ──
        try:
            from l1.kernel.event import get_bus

            # String-typed emit under "error_log" so _on_error_event and SSE
            # type filters (types={"error_log"}) receive the event; push_event
            # would force SignalType.TASK_ASSIGN and break the contract.
            get_bus().emit_event("error_log", result_entry.to_dict(), source=component)
        except Exception as e:
            logger.warning("error_bus: event push failed: %s", e)

        # ── Push to MonitorBus ──
        try:
            from l3.bus.monitor_bus import MonitorEvent
            from l3.bus.monitor_bus import get_bus as get_mbus

            sev = {"DEBUG": "info", "INFO": "info", "WARNING": "warn", "ERROR": "crit", "CRITICAL": "crit"}.get(
                level, "warn"
            )
            get_mbus().emit(
                MonitorEvent(
                    type="error.bus",
                    source="error_bus",
                    severity=sev,
                    agent_id=agent_id,
                    message=f"[{error_code}] {message[:LOG_TRUNC_200]}",
                    data={
                        "level": level,
                        "service": service,
                        "component": component,
                        "task_id": task_id,
                        "fingerprint": result_entry.fingerprint,
                    },
                )
            )
        except Exception as e:
            logger.warning("error_bus: monitor push failed: %s", e)

        # Invalidate stats cache
        self._stats_ts = 0.0

        return {"success": True, "entry": result_entry.to_dict()}

    # ── EventBus callback ──

    def _on_error_event(self, signal: Any) -> None:
        """Receive error events from EventBus → push to all SSE clients"""
        data = signal.data if hasattr(signal, "data") else signal
        with self._sse_lock:
            dead: list[queue.Queue] = []
            for q in self._sse_clients:
                try:
                    q.put_nowait(data)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._sse_clients.remove(q)

    # ── SSE ──

    def subscribe_sse(self) -> queue.Queue:
        """Create a subscription queue for an SSE client."""
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._sse_lock:
            self._sse_clients.append(q)
        return q

    def unsubscribe_sse(self, q: queue.Queue) -> None:
        """Remove an SSE client queue."""
        with self._sse_lock:
            if q in self._sse_clients:
                self._sse_clients.remove(q)

    # ── Query ──

    def query(
        self,
        level: str | None = None,
        error_code: str | None = None,
        component: str | None = None,
        service: str | None = None,
        agent_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
        offset: int = 0,
        limit: int = ERROR_BUS_QUERY_LIMIT,
    ) -> dict:
        """Query error logs by criteria (paginated, descending by time)."""
        with self._lock:
            results = list(self._buffer)

        # Filter
        if level:
            results = [e for e in results if e.level == level.upper()]
        if error_code:
            results = [e for e in results if e.error_code == error_code]
        if component:
            results = [e for e in results if e.component == component]
        if service:
            results = [e for e in results if e.service == service]
        if agent_id:
            results = [e for e in results if e.agent_id == agent_id]
        if since:
            results = [e for e in results if e.timestamp >= since]
        if until:
            results = [e for e in results if e.timestamp <= until]

        # Descending by time
        results.sort(key=lambda e: e.timestamp, reverse=True)

        total = len(results)
        page = results[offset : offset + limit]

        return {
            "success": True,
            "total": total,
            "offset": offset,
            "limit": limit,
            "entries": [e.to_dict() for e in page],
        }

    def get_by_fingerprint(self, fingerprint: str) -> dict | None:
        """Get a single error detail by fingerprint."""
        with self._lock:
            entry = self._fingerprint_index.get(fingerprint)
            if entry:
                # Collect all timestamps where this fingerprint appeared
                return entry.to_dict()
            return None

    def stats(self) -> dict:
        """Error statistics: aggregated by level / error_code / component, with cache."""
        now = time.time()
        if now - self._stats_ts < 2.0 and self._stats_cache:
            return self._stats_cache

        with self._lock:
            entries = list(self._buffer)

        by_level: dict[str, int] = {}
        by_error_code: dict[str, int] = {}
        by_component: dict[str, int] = {}
        top_sources: dict[str, int] = {}
        agents: set[str] = set()

        for e in entries:
            by_level[e.level] = by_level.get(e.level, 0) + 1
            by_error_code[e.error_code] = by_error_code.get(e.error_code, 0) + 1
            by_component[e.component] = by_component.get(e.component, 0) + 1
            src = f"{e.source}" if e.source else "unknown"
            top_sources[src] = top_sources.get(src, 0) + 1
            if e.agent_id:
                agents.add(e.agent_id)

        # Sort top_sources, take top ERROR_BUS_TOP_SOURCES
        sorted_sources = sorted(top_sources.items(), key=lambda x: -x[1])[:ERROR_BUS_TOP_SOURCES]

        result = {
            "success": True,
            "total": len(entries),
            "by_level": by_level,
            "by_error_code": by_error_code,
            "by_component": by_component,
            "top_sources": [{"source": s, "count": c} for s, c in sorted_sources],
            "agents": len(agents),
        }

        # Disk file count
        try:
            log_dir = _LOG_DIR
            if log_dir.exists():
                result["disk_files"] = len(list(log_dir.glob(LOG_ROTATE_GLOB)))
                result["log_dir"] = str(log_dir)
        except Exception:
            logger.debug("error_bus: stats disk check failed")

        self._stats_cache = result
        self._stats_ts = now
        return result

    def trend(self, window_minutes: int = 60, bucket_minutes: int = 10) -> dict:
        """Error trend: bucket statistics by time window.

        Args:
            window_minutes: Lookback window (default 60 minutes)
            bucket_minutes: Bucket size (default 10 minutes)

        Returns:
            {"buckets": [{"bucket": "ISO8601", "count": int}, ...]}
        """
        now = time.time()
        since = now - window_minutes * 60

        with self._lock:
            entries = [e for e in self._buffer if e.timestamp >= since]

        # Bucketing
        bucket_size = bucket_minutes * 60
        buckets: dict[int, int] = defaultdict(int)

        for e in entries:
            bucket_ts = int(e.timestamp // bucket_size) * bucket_size
            buckets[bucket_ts] += 1

        result = [
            {
                "bucket": datetime.fromtimestamp(ts, tz=UTC).isoformat(),
                "count": count,
            }
            for ts, count in sorted(buckets.items())
        ]

        return {"success": True, "window_minutes": window_minutes, "buckets": result}

    def recent(self, limit: int = 50) -> dict:
        """Get the most recent N errors (fast)."""
        with self._lock:
            entries = list(self._buffer)[-limit:]
        entries.reverse()
        return {
            "success": True,
            "entries": [e.to_dict() for e in entries],
            "count": len(entries),
        }

    def clear(self, before: float | None = None) -> dict:
        """Clear the error buffer (optionally before a given timestamp)."""
        with self._lock:
            if before is None:
                removed = len(self._buffer)
                self._buffer.clear()
                self._fingerprint_index.clear()
            else:
                remaining = [e for e in self._buffer if e.timestamp >= before]
                removed = len(self._buffer) - len(remaining)
                self._buffer = deque(remaining, maxlen=self._max_entries)
                self._fingerprint_index = {e.fingerprint: e for e in remaining}
        self._stats_ts = 0.0
        return {"success": True, "removed": removed}

    def export(self, path: str = "") -> dict:
        """Export error logs to a JSON file."""
        with self._lock:
            entries = [e.to_dict() for e in self._buffer]

        out_path = path or str(_LOG_DIR / ERROR_EXPORT_FILE.format(ts=int(time.time())))
        try:
            Path(out_path).write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"success": True, "path": out_path, "count": len(entries)}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════
# Global singleton
# ══════════════════════════════════════════════════════════════════════

_bus: ErrorBus | None = None
_bus_lock = threading.Lock()


def get_bus() -> ErrorBus:
    """Get the ErrorBus singleton, starting it on first call. Returns the bus."""
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = ErrorBus()
                _bus.start()  # triggers _on_start → EventBus subscription
    return _bus


def reset_bus() -> None:
    """Reset the ErrorBus singleton. Returns None."""
    global _bus
    if _bus:
        _bus.stop()
    _bus = None
