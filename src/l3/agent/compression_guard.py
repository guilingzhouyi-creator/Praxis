"""Recursive-compression threshold + circuit breaker (Phase 3.1, B6).

Two cooperating guards prevent unbounded recursive compression on L3A
sessions:

  - Recursive-compression threshold (default OFF, threshold 0): when
    enabled, a session that reaches ``recursion_threshold`` consecutive
    compression passes stops further recursive compression and surfaces a
    manual-intervention prompt (protects information integrity).
  - Circuit breaker (default ON): when the threshold is hit (or a
    compression error storm is detected), the breaker trips — compression
    pauses, the event is logged (PMU + logger) for later analysis, and the
    operator is told how to reset it.

Operator switches (API ``/api/v2/memory/compression-guard`` + L2 ``/memory
compression-guard``). Both degrade gracefully and never raise.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from l1.kernel.params.system import (
    COMPRESSION_BREAKER_ENABLED_DEFAULT,
    COMPRESSION_RECURSION_THRESHOLD_DEFAULT,
)

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {
    "recursion_threshold": COMPRESSION_RECURSION_THRESHOLD_DEFAULT,
    "breaker_enabled": COMPRESSION_BREAKER_ENABLED_DEFAULT,
    "tripped": False,
    "trip_reason": "",
    "trip_at": 0.0,
    "per_session_depth": {},  # session_id -> consecutive compression count
}
_lock = threading.RLock()

# Config-file driven operator switches (l1.kernel.settings → SettingsCenter).
_SWITCH_RECURSION = "l3a.compression_guard.recursion_threshold"
_SWITCH_BREAKER = "l3a.compression_guard.breaker_enabled"
_hydrated = False


def _hydrate() -> None:
    """Hydrate the guard-switch cache from SettingsCenter (config-file driven)."""
    global _hydrated
    if _hydrated:
        return
    with _lock:
        if _hydrated:
            return
        try:
            from l1.kernel.settings import get_settings

            _state["recursion_threshold"] = int(
                get_settings().get(_SWITCH_RECURSION, COMPRESSION_RECURSION_THRESHOLD_DEFAULT)
            )
            _state["breaker_enabled"] = bool(get_settings().get(_SWITCH_BREAKER, COMPRESSION_BREAKER_ENABLED_DEFAULT))
        except Exception:
            logger.debug("compression_guard: settings hydrate skipped", exc_info=True)
        _hydrated = True


def _persist(recursion_threshold: int | None = None, breaker_enabled: bool | None = None) -> None:
    """Persist guard-switch overrides to SettingsCenter (best-effort)."""
    try:
        from l1.kernel.settings import get_settings

        s = get_settings()
        if recursion_threshold is not None:
            s.set(_SWITCH_RECURSION, int(recursion_threshold))
        if breaker_enabled is not None:
            s.set(_SWITCH_BREAKER, bool(breaker_enabled))
    except Exception:
        logger.debug("compression_guard: settings persist skipped", exc_info=True)


def guard_status() -> dict:
    """Return the compression-guard switch + breaker state."""
    _hydrate()
    with _lock:
        return {
            "recursion_threshold": int(_state["recursion_threshold"]),
            "breaker_enabled": bool(_state["breaker_enabled"]),
            "tripped": bool(_state["tripped"]),
            "trip_reason": str(_state["trip_reason"]),
            "trip_at": float(_state["trip_at"]),
        }


def set_guard_switches(recursion_threshold: int | None = None, breaker_enabled: bool | None = None) -> dict:
    """Set the compression-guard operator switches.

    Args:
        recursion_threshold: max consecutive compression passes per session
            (0 = recursive compression off). Setting a value also resets a
            tripped breaker (operator intervention).
        breaker_enabled: circuit-breaker master switch.

    Returns:
        dict with success flag and the effective state.
    """
    _hydrate()
    final_threshold = max(0, int(recursion_threshold)) if recursion_threshold is not None else None
    final_breaker = bool(breaker_enabled) if breaker_enabled is not None else None
    with _lock:
        if final_threshold is not None:
            _state["recursion_threshold"] = final_threshold
            # Operator intervention: reset a tripped breaker.
            _state["tripped"] = False
            _state["trip_reason"] = ""
            _state["trip_at"] = 0.0
            _state["per_session_depth"] = {}
        if final_breaker is not None:
            _state["breaker_enabled"] = final_breaker
            if not _state["breaker_enabled"]:
                _state["tripped"] = False
    _persist(recursion_threshold=final_threshold, breaker_enabled=final_breaker)
    return {"success": True, **guard_status()}


def reset_guard() -> None:
    """Reset all compression-guard state (tests / lifecycle)."""
    global _hydrated
    with _lock:
        _state["recursion_threshold"] = COMPRESSION_RECURSION_THRESHOLD_DEFAULT
        _state["breaker_enabled"] = COMPRESSION_BREAKER_ENABLED_DEFAULT
        _state["tripped"] = False
        _state["trip_reason"] = ""
        _state["trip_at"] = 0.0
        _state["per_session_depth"] = {}
        _hydrated = False
    try:
        from l1.kernel.settings import get_settings

        get_settings().reset(_SWITCH_RECURSION)
        get_settings().reset(_SWITCH_BREAKER)
    except Exception:
        logger.debug("compression_guard: settings reset skipped", exc_info=True)


def _trip(reason: str) -> None:
    """Trip the breaker: pause compression and record the event."""
    with _lock:
        _state["tripped"] = True
        _state["trip_reason"] = reason
        _state["trip_at"] = time.time()
        _state["per_session_depth"] = {}
    logger.warning("compression_guard: circuit breaker TRIPPED — %s", reason)
    try:
        from l3.tool_system.security_evidence import record_evidence

        record_evidence(
            phase="l3a_compress",
            gate="circuit_breaker",
            decision="BLOCK",
            target="session_compress",
            source="compression_guard",
            tags={"reason": reason},
        )
    except Exception:
        logger.debug("compression_guard: evidence record skipped")


def check_recursion(session_id: str) -> dict:
    """Guard check before a session's compression pass.

    Args:
        session_id: the session about to be compressed.

    Returns:
        ``{"success": True, "blocked": False, ...}`` when the pass may run;
        ``{"success": False, "blocked": True, "error": <manual prompt>}``
        when the threshold or breaker stops it.
    """
    _hydrate()
    with _lock:
        tripped = bool(_state["tripped"])
        breaker_enabled = bool(_state["breaker_enabled"])
        threshold = int(_state["recursion_threshold"])
        if tripped:
            return {
                "success": False,
                "blocked": True,
                "error": "compression paused by circuit breaker — "
                "operator intervention required (set recursion_threshold to reset)",
            }
        if breaker_enabled and threshold > 0:
            depth = int(_state["per_session_depth"].get(session_id, 0))
            if depth >= threshold:
                _trip(f"session {session_id} reached recursive-compression threshold {threshold}")
                return {
                    "success": False,
                    "blocked": True,
                    "error": f"recursive-compression threshold ({threshold}) reached — "
                    "compression stopped, manual intervention required",
                }
    return {"success": True, "blocked": False}


def record_compress_pass(session_id: str) -> None:
    """Record one compression pass for a session (threshold bookkeeping)."""
    with _lock:
        _state["per_session_depth"][session_id] = int(_state["per_session_depth"].get(session_id, 0)) + 1


def reset_session_depth(session_id: str) -> None:
    """Reset a session's compression depth (e.g. after operator reset)."""
    with _lock:
        _state["per_session_depth"].pop(session_id, None)
