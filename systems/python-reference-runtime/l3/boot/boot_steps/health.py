"""Boot step — post-boot health verification.

Extracted from ``boot_steps.py``.  ``_post_boot_health_check`` probes the
core subsystems after boot; it never blocks boot completion.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _post_boot_health_check() -> dict:
    """Verify core subsystems are operational after boot. Does not block."""
    checks: dict[str, Any] = {}
    try:
        from l3.memory.memory import get_memory

        m = get_memory()
        checks["memory"] = "ok" if m is not None else "unavailable"
    except Exception as e:
        checks["memory"] = f"error: {e}"
    try:
        from l3.card.card_registry import get_registry

        r = get_registry()
        checks["card_registry"] = "ok" if r is not None else "unavailable"
    except Exception as e:
        checks["card_registry"] = f"error: {e}"
    try:
        from l3.scheduler.scheduler import get_time_scheduler

        s = get_time_scheduler()
        checks["scheduler"] = "ok" if s is not None else "unavailable"
    except Exception as e:
        checks["scheduler"] = f"error: {e}"
    try:
        from l1.kernel.device import get_device_manager

        d = get_device_manager()
        devs = d.list()
        checks["devices"] = f"{len(devs)} registered"
    except Exception as e:
        checks["devices"] = f"error: {e}"
    try:
        from l3.agent_terminal import get_terminals

        terms = get_terminals()
        checks["terminals"] = f"{len(terms)} active"
    except Exception as e:
        checks["terminals"] = f"error: {e}"
    all_ok = all(v.startswith("ok") or v.endswith("registered") or "active" in v for v in checks.values())
    checks["_all_ok"] = all_ok
    return checks
