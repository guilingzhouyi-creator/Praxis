"""ErrorBus trace-id context — unified request correlation.

Extracted from ``error_bus/core.py``: a contextvar carries one trace id
request → agent → tool → error without threading it through every
signature; ``capture()`` auto-reads it. ``propagate_context`` lets bare
threads inherit the caller's contextvars (needed on Python 3.11).
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("praxis_trace_id", default="")


def get_trace_id() -> str:
    """Return the current context's trace id (empty if none set)."""
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> str:
    """Set the current context's trace id; returns the new value."""
    _trace_id_var.set(trace_id)
    return trace_id


@contextmanager
def trace_scope(trace_id: str) -> Generator[str, None, None]:
    """Context manager: set trace_id for the scope, restore on exit.

    Usage::

        with trace_scope(call_id):
            ...  # captures inside see trace_id
    """
    token = _trace_id_var.set(trace_id)
    try:
        yield trace_id
    finally:
        _trace_id_var.reset(token)


def propagate_context(fn: Callable) -> Callable:
    """Wrap *fn* so it runs inside a copy of the current contextvars context.

    Bare ``threading.Thread`` targets do not inherit the caller's context on
    Python 3.11 (3.12+ copies by default), so a trace_id set in the request
    context would be lost in spawned threads. Apply this wrapper at thread
    spawn points: ``Thread(target=propagate_context(fn))``.
    """
    ctx = contextvars.copy_context()

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        return ctx.run(fn, *args, **kwargs)

    return _wrapped
