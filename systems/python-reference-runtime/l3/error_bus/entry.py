"""ErrorBus data model — structured error log entry + fingerprint helpers.

Extracted from ``error_bus/core.py``: ``ErrorLogEntry`` carries the richer
error-specific fields (error_code/component/source/stack_trace/context/
fingerprint/count) on top of the generic log fields, and the dedup
fingerprint / caller-source / exception-formatting helpers used by the bus.
"""

from __future__ import annotations

import hashlib
import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from l1.kernel.params.system import (
    HASH_TRUNC_LONG,
    HASH_TRUNC_MEDIUM,
    LOG_TRUNC_100,
    LOG_TRUNC_500,
    LOG_TRUNC_1000,
)

logger = logging.getLogger(__name__)


@dataclass
class ErrorLogEntry:
    """Structured error log entry — richer than the generic LogEntry.

    Adds to the LogEntry from services/log.py:
      - error_code: Unified error code (linked with kernel/errors.py)
      - component:  Component layer (kernel / services / tools / api / cli)
      - source:     Source location (file:line)
      - stack_trace:Exception stack trace
      - context:    Additional key-value pairs
      - fingerprint:Deduplication fingerprint
      - count:      Cumulative occurrence count for the same fingerprint
    """

    # ── Basic fields ──
    level: str  # "ERROR" | "CRITICAL" | "WARN"
    service: str  # e.g. "kernel/allocator", "services/agent_loop"
    message: str
    timestamp: float = field(default_factory=time.time)
    agent_id: str = ""
    task_id: str = ""
    trace_id: str = ""  # unified correlation id: request → agent → tool → error

    # ── Error-specific fields ──
    error_code: str = "E_INTERNAL"
    component: str = "kernel"  # kernel / services / tools / api / cli
    source: str = ""  # e.g. "kernel/allocator.py:77"
    stack_trace: str = ""
    context: dict = field(default_factory=dict)

    # ── Deduplication fields ──
    fingerprint: str = ""
    count: int = 1

    def __post_init__(self) -> None:
        if not self.fingerprint:
            self.fingerprint = _compute_fingerprint(
                self.level,
                self.error_code,
                self.source,
                self.message,
            )

    def to_dict(self) -> dict:
        """Serialize the entry to a dict."""
        return {
            "id": self.fingerprint[:HASH_TRUNC_MEDIUM],
            "level": self.level,
            "error_code": self.error_code,
            "component": self.component,
            "service": self.service,
            "message": self.message[:LOG_TRUNC_500],
            "source": self.source,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat(),
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "stack_trace": (self.stack_trace or "")[:LOG_TRUNC_1000],
            "context": self.context,
            "count": self.count,
        }


def _compute_fingerprint(
    level: str,
    error_code: str,
    source: str,
    message: str,
) -> str:
    """Compute deduplication fingerprint — sha256(level + error_code + source + message[:LOG_TRUNC_100]) → hex[:16]"""
    raw = f"{level}|{error_code}|{source}|{message[:LOG_TRUNC_100]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:HASH_TRUNC_LONG]


def _caller_source(depth: int = 2) -> str:
    """Auto-detect caller location — returns 'file.py:line'"""
    import inspect

    try:
        frame = inspect.currentframe()
        # Skip up depth levels: capture() → error() → caller()
        for _ in range(depth):
            if frame and frame.f_back:
                frame = frame.f_back
        if frame:
            return f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}"
    except Exception:
        logger.debug("error_bus: caller resolve failed")
    return "unknown"


def _format_exc(exc: Exception | None) -> str:
    """Format exception stack trace, truncated to first 1000 characters"""
    if not exc:
        return ""
    lines = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return lines[:LOG_TRUNC_1000]
