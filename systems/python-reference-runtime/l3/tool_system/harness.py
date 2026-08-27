"""Harness mode runtime state — runtime override over the static config.

The pipeline reads ``get_harness_mode()`` on every execution. The value
resolves from the runtime override (set via API or L2 Shell) first, then
falls back to the ``harness.mode`` entry in ``config/praxis.yaml``, then to
the params default (governed). Switching to ``minimal`` requires an explicit
risk confirmation (``confirmed=True``) — the caller asserts user acceptance
of unguarded tool execution; the safety bottom line (constitution, gatechain,
sandbox, reference-channel recording) is enforced by the pipeline itself and
can never be disabled through this module.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from l1.kernel.discovery import get_tool_config
from l1.kernel.params.tool import (
    HARNESS_MODE_DEFAULT,
    HARNESS_MODES,
    HARNESS_PRESETS,
)

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {"mode": None}
_static_mode: str | None = None
_lock = threading.RLock()

BOTTOM_LINE = "constitution + gatechain + sandbox + reference-channel recording"


def _resolve_static() -> str:
    """Resolve the static config value without touching the cache."""
    static = str(get_tool_config("harness_mode", HARNESS_MODE_DEFAULT)).lower()
    return static if static in HARNESS_MODES else HARNESS_MODE_DEFAULT


def get_harness_mode() -> str:
    """Return the effective harness mode (override → config → default)."""
    global _static_mode
    with _lock:
        override = _state["mode"]
        if override in HARNESS_MODES:
            return override
        if _static_mode is None:
            _static_mode = _resolve_static()
        return _static_mode


def invalidate_harness_static() -> None:
    """Drop the cached static resolution after a praxis.yaml harness reload."""
    global _static_mode
    with _lock:
        _static_mode = None


def set_harness_mode(mode: str, confirmed: bool = False, source: str = "api") -> dict:
    """Switch the harness mode at runtime.

    Args:
        mode: one of HARNESS_MODES (governed / semi / minimal).
        confirmed: explicit user risk acceptance; REQUIRED for ``minimal``.
        source: caller identity ("api" / "shell" / ...) for the audit trail.

    Returns:
        dict with success flag, effective mode, and risk note when minimal.
    """
    mode = str(mode or "").lower()
    if mode not in HARNESS_MODES:
        return {"success": False, "error": f"invalid harness mode: {mode}", "modes": list(HARNESS_MODES)}
    # B8 authorization boundary: harness modes forbidden under offensive
    # posture (minimal drops approval + rate limiting) are rejected here,
    # before any state change or evidence recording.
    try:
        from l3.tool_system.posture_matrix import get_posture_matrix

        bound = get_posture_matrix().validate_harness(mode)
        if not bound.get("success"):
            return {"success": False, "error": bound.get("error", "harness mode forbidden by posture matrix")}
    except Exception as e:
        # WS2.2 fail-closed: an unavailable posture matrix must refuse the
        # mode change, never silently continue with the old behavior.
        return {"success": False, "error": f"harness posture boundary check failed: {e}"}
    if mode == "minimal" and not confirmed:
        return {
            "success": False,
            "error": "minimal mode requires explicit risk confirmation "
            "(confirm_risk=true): approval, rate limit and pool "
            "gates are disabled; constitution/gatechain/sandbox/"
            "recording stay enforced",
            "modes": list(HARNESS_MODES),
        }
    with _lock:
        _state["mode"] = mode
        _state["source"] = source
    # Unified control bar: keep the presentation mode in lockstep with the
    # harness level (code → run_code programmatic presentation; the other
    # levels → native function-calling).
    try:
        from l3.tool_system.tool_presentation import set_presentation_mode as _set_presentation

        _pres = str(HARNESS_PRESETS.get(mode, {}).get("presentation", "native"))
        _set_presentation(_pres, source="harness")
    except Exception:
        logger.debug("harness: presentation sync skipped", exc_info=True)
    # Evidence chain: a confirmed minimal downgrade opens a "downgrade" chain.
    try:
        from l3.tool_system.security_evidence import DECISION_CHANGE, get_evidence, record_evidence

        record_evidence(
            phase="harness",
            gate="harness_mode",
            decision=DECISION_CHANGE,
            target=f"mode:{mode}",
            source=source,
            tags={"confirmed": str(bool(confirmed)).lower()},
            chain_kind="downgrade" if mode == "minimal" else "ambient",
        )
        if mode != "minimal":
            get_evidence().close_open(kind="downgrade")
    except Exception:
        pass
    return {
        "success": True,
        "mode": mode,
        "source": source,
        "note": None if mode != "minimal" else f"risk user-assumed; bottom line ({BOTTOM_LINE}) still enforced",
    }


def reset_harness_mode() -> dict:
    """Clear the runtime override; effective mode returns to static config."""
    global _static_mode
    with _lock:
        _state["mode"] = None
        _state["source"] = "config"
        static = _static_mode
        _static_mode = None
    return {"success": True, "mode": static if static is not None else _resolve_static(), "source": "config"}


def harness_status() -> dict:
    """Return the current mode plus the switchable matrix and bottom line."""
    with _lock:
        source = _state.get("source", "config")
    return {"mode": get_harness_mode(), "source": source, "modes": list(HARNESS_MODES), "bottom_line": BOTTOM_LINE}
