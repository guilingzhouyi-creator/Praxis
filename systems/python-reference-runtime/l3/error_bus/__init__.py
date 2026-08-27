"""ErrorBus — unified error log bus.

Public package surface — re-exports the implementation from ``core.py``
(ErrorLogEntry / ErrorBus / capture helpers) and the API handlers from
``api.py`` so all existing ``from l3.error_bus import …`` call sites keep
working unchanged.
"""

from __future__ import annotations

from .api import (  # noqa: F401 — re-export for callers
    handle_log_errors,
    handle_log_errors_clear,
    handle_log_errors_detail,
    handle_log_errors_export,
    handle_log_errors_stats,
    handle_log_errors_trend,
)
from .core import (  # noqa: F401 — re-export for callers
    ErrorBus,
    ErrorLogEntry,
    capture,
    capture_exception,
    error_boundary,
    get_bus,
    reset_bus,
)

__all__ = [
    "ErrorBus",
    "ErrorLogEntry",
    "capture",
    "capture_exception",
    "error_boundary",
    "get_bus",
    "reset_bus",
    "handle_log_errors",
    "handle_log_errors_clear",
    "handle_log_errors_detail",
    "handle_log_errors_export",
    "handle_log_errors_stats",
    "handle_log_errors_trend",
]
