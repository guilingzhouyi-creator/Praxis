"""Violation monitor — department overreach output detection (Phase D).

The second TODO-style monitor: when department division is active, an
agent's output is classified (build / test / review content) and compared
against its department's permission scope. Producing content that belongs
to another department is an overreach:

  - light volume (<= VIOLATION_LIGHT_MAX overreach outputs) is tolerated —
    the judging system permits lightweight test work by a build agent;
  - heavy volume (>= VIOLATION_HEAVY_THRESHOLD) is stopped — the monitor
    emits a stop command (event-bus message) and returns a refusal.

The monitor itself is an optimization, never a gate: a disabled monitor, an
inactive division, a classification failure, or an emit failure all degrade
to "allow" (no-op) instead of raising.

Operator switches (three channels): settings flat key
``departments.violation_monitor`` (default off), API
``/api/v2/departments/violation-monitor``, L2 ``departments monitor``.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from l1.kernel.params.agent import (
    VIOLATION_HEAVY_THRESHOLD,
    VIOLATION_LIGHT_MAX,
    VIOLATION_MONITOR_ENABLED_DEFAULT,
)

logger = logging.getLogger(__name__)

# Output classification: content markers per identity field. Markers are
# substring patterns (lowercase); the monitor counts overreach per agent.
_CONTENT_MARKERS: dict[str, tuple[str, ...]] = {
    "build": ("def ", "class ", "implement", "refactor"),
    "test": ("def test_", "assert ", "pytest", "test_matrix"),
    "review": ("review", "audit", "approve", "cross-check"),
}

_state: dict[str, Any] = {"enabled": VIOLATION_MONITOR_ENABLED_DEFAULT}
_lock = threading.RLock()
_overreach: dict[str, int] = {}  # agent_id -> overreach counter
# Memoized role -> owning-department lookup (check_output hot path). Cleared
# on reset; department roles are config/bootstrap-time, so the cache stays
# valid for the process lifetime.
_dept_cache: dict[str, str] = {}


def enabled() -> bool:
    """Return whether the monitor is active (settings switch AND division).

    Both the settings flat key and the department division must be on — a
    switch-on with fewer than CELL_DEPARTMENT_MIN cells is inert (matches
    the requirement: "even if started it has no effect below 2+ cells").
    """
    try:
        from l1.kernel.settings import get_settings
        from l3.cell.department import get_department_manager

        if not bool(get_settings().get("departments.violation_monitor", VIOLATION_MONITOR_ENABLED_DEFAULT)):
            return False
        return bool(get_department_manager().active())
    except Exception as e:
        logger.debug("violation_monitor: enabled check skipped: %s", e)
        return False


def set_enabled(value: bool | None = None) -> dict:
    """Set the operator switch via the settings flat key (all channels unified).

    API PUT, L2 ``departments monitor``, and the generic settings surface all
    land on the same ``departments.violation_monitor`` key that ``enabled()``
    reads — a set always takes effect (division still gates it). ``None``
    keeps the current setting.
    """
    if value is None:
        return {"success": True, "enabled": enabled()}
    try:
        from l1.kernel.settings import get_settings

        get_settings().set("departments.violation_monitor", bool(value))
    except Exception as e:
        logger.warning("violation_monitor: switch persist skipped: %s", e)
    with _lock:
        _state["enabled"] = bool(value)
    return {"success": True, "enabled": enabled()}


def status() -> dict:
    """Return monitor status (switch, counters, thresholds)."""
    with _lock:
        return {
            "enabled": enabled(),
            "switch": _state["enabled"],
            "light_max": VIOLATION_LIGHT_MAX,
            "heavy_threshold": VIOLATION_HEAVY_THRESHOLD,
            "overreach": dict(_overreach),
        }


def _classify(text: str) -> str:
    """Classify output text into one of build/test/review ("" when unsure)."""
    low = (text or "").lower()
    scores: dict[str, int] = {}
    for identity, markers in _CONTENT_MARKERS.items():
        scores[identity] = sum(1 for m in markers if m in low)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else ""


def classify_output(text: str) -> str:
    """Public classification (no state mutation). Returns identity or ""."""
    return _classify(text)


def check_output(agent_id: str, cell_id: str, role: str, text: str) -> dict:
    """Check one agent output against its department scope.

    Args:
        agent_id: producing agent.
        cell_id: the agent's Cell (scope lookup).
        role: the agent's role (scope lookup).
        text: the produced output content.

    Returns:
        dict with allowed (bool) and optional stop/reason fields. Always
        allows (no-op) when the monitor is off or classification fails.
    """
    try:
        if not enabled():
            return {"allowed": True, "monitored": False}
        from l3.cell.department import get_department_manager

        mgr = get_department_manager()
        # The agent's owning department (by role); memoized per role.
        owner_id = _dept_cache.get(role)
        if owner_id is None:
            owner_id = mgr.department_for_role(role) or ""
            _dept_cache[role] = owner_id
        if not owner_id:
            return {"allowed": True, "monitored": True, "reason": "no department for role"}
        owner = mgr._departments.get(owner_id)
        content_type = _classify(text)
        if not content_type:
            return {"allowed": True, "monitored": True, "reason": "unclassified output"}
        # Overreach: content belongs to a different identity than the owner's scope.
        if owner is not None and owner.permission_scope and content_type not in owner.permission_scope:
            return _handle_overreach(agent_id, owner_id, content_type)
        return {"allowed": True, "monitored": True}
    except Exception as e:
        logger.debug("violation_monitor: check skipped: %s", e)
        return {"allowed": True, "monitored": False}


def _handle_overreach(agent_id: str, owner_id: str, content_type: str) -> dict:
    """Count the overreach; stop when the heavy threshold is crossed."""
    with _lock:
        count = _overreach.get(agent_id, 0) + 1
        _overreach[agent_id] = count
        stop = count >= VIOLATION_HEAVY_THRESHOLD
        light = count <= VIOLATION_LIGHT_MAX
    if stop:
        _emit_stop(agent_id, owner_id, content_type, count)
        return {
            "allowed": False,
            "monitored": True,
            "stop": True,
            "reason": f"{content_type} output outside {owner_id} scope ({count} overreach)",
        }
    if not light:
        return {
            "allowed": True,
            "monitored": True,
            "warning": f"{content_type} output outside {owner_id} scope ({count}/{VIOLATION_HEAVY_THRESHOLD})",
        }
    return {"allowed": True, "monitored": True, "light": True}


def _emit_stop(agent_id: str, owner_id: str, content_type: str, count: int) -> None:
    """Emit a stop command via the event bus (best-effort, never raises)."""
    try:
        from l1.kernel.event import get_bus

        get_bus().emit_event(
            "violation_monitor.stop",
            {
                "agent_id": agent_id,
                "department": owner_id,
                "content_type": content_type,
                "overreach_count": count,
            },
            source="violation_monitor",
        )
    except Exception as e:
        logger.debug("violation_monitor: stop emit skipped: %s", e)


def reset_violation_monitor() -> None:
    """Reset switch + counters (tests / lifecycle)."""
    global _overreach, _dept_cache
    with _lock:
        _state["enabled"] = VIOLATION_MONITOR_ENABLED_DEFAULT
        _overreach = {}
        _dept_cache = {}
