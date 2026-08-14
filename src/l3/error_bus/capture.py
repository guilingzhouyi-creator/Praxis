"""ErrorBus capture facade — one-line error capture entry points.

Extracted from ``error_bus/core.py``: ``capture`` / ``capture_exception``
/ ``error_boundary`` are the global quick-access helpers callers use in
their ``except`` blocks. They resolve the singleton bus lazily (import
inside the function) so this module never creates an import cycle with
``core.py`` (which re-exports them).
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def error_boundary(
    message: str = "",
    error_code: str = "E_INTERNAL",
    component: str = "kernel",
    agent_id: str = "",
    task_id: str = "",
    re_raise: bool = False,
) -> Generator:
    """Context manager — capture all exceptions within a block into ErrorBus.

    Usage:
        with error_boundary("agent loop failed", component="services"):
            ...

    By default exceptions are consumed (not re-raised).
    Set re_raise=True to propagate after capture.
    """
    try:
        yield
    except Exception as e:
        capture(
            message or str(e), error_code=error_code, component=component, exc=e, agent_id=agent_id, task_id=task_id
        )
        if re_raise:
            raise


def capture(
    message: str,
    error_code: str = "E_INTERNAL",
    component: str = "kernel",
    exc: Exception | None = None,
    agent_id: str = "",
    task_id: str = "",
    context: dict | None = None,
) -> dict:
    """Simplest error capture entry point — one-line replacement for all except blocks.

    Usage:
        try:
            ...
        except Exception as e:
            capture("memory compact failed", exc=e, component="services")

    Auto-extracts:
      - source: caller's file:line from the call stack
      - stack_trace: traceback from exc
      - service: reuses the component value

    Returns:
        {"success": True, "entry": {...}}
    """
    from .core import get_bus
    from .entry import _caller_source, _format_exc
    from .trace import get_trace_id

    # Best-effort ingest: never let an ErrorBus failure escape into the
    # caller's exception handler (previously a raise here would replace
    # the original exception and break guaranteed control flow, e.g. the
    # agent-loop context abort or the daemon tick loop).
    try:
        bus = get_bus()
        source = _caller_source(depth=2)
        stack_trace = _format_exc(exc) if exc else ""
        return bus.error(
            message=message,
            error_code=error_code,
            component=component,
            service=component,
            source=source,
            stack_trace=stack_trace,
            agent_id=agent_id,
            task_id=task_id,
            trace_id=get_trace_id(),
            context=context or {},
        )
    except Exception as e:
        logger.debug("error_bus: capture failed: %s", e)
        return {"success": False, "error": f"error_bus capture failed: {e}"}


def capture_exception(
    exc: Exception,
    message: str = "",
    error_code: str = "E_INTERNAL",
    component: str = "kernel",
    agent_id: str = "",
    task_id: str = "",
    context: dict | None = None,
) -> dict:
    """Capture directly from an Exception object.

    Usage:
        except Exception as e:
            capture_exception(e, "XXX failed", component="services")
    """
    from .core import get_bus

    try:
        bus = get_bus()
        return bus.exception(
            exc=exc,
            message=message,
            error_code=error_code,
            component=component,
            agent_id=agent_id,
            task_id=task_id,
            context=context or {},
        )
    except Exception as e:
        logger.debug("error_bus: capture_exception failed: %s", e)
        return {"success": False, "error": f"error_bus capture failed: {e}"}
