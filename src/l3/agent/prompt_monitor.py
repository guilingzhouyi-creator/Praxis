"""System-prompt bypass monitor (3.2, P1-⑥) — usage/success/failure analytics.

Quantifies each system prompt's usage frequency, success rate, and failure
rate, and correlates the metrics with the reference channel (RC) for
further prompt optimization. The monitor is a BYPASS: it never blocks the
main prompt flow and degrades to a no-op on any error.

Mode semantics: the monitor is DISABLED in production and enabled in
engineering/debug mode — the operator switch (API + L2 Shell) defaults to
OFF (production). When enabled, every ``get_prompt`` hit records a usage
sample and every card/task outcome records a success/failure sample keyed
by the driving prompt key.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from l1.kernel.params.system import PROMPT_MONITOR_ENABLED_DEFAULT

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {"enabled": PROMPT_MONITOR_ENABLED_DEFAULT}
_lock = threading.RLock()

# key -> {"used": int, "ok": int, "fail": int}
_metrics: dict[str, dict[str, int]] = {}


def prompt_monitor_status() -> dict:
    """Return the bypass-monitor switch state."""
    with _lock:
        return {"enabled": bool(_state["enabled"]), "tracked_keys": len(_metrics)}


def set_prompt_monitor(
    enabled: bool | None = None,
    *,
    source: str = "operator",
    internal: bool = False,
) -> dict:
    """Set the prompt-monitor operator switch.

    Args:
        enabled: master switch (None = keep current). Default OFF =
            production; ON = engineering/debug mode.
        source: caller identity for the audit trail.
        internal: trusted system transition from EngineeringDebugManager.

    Returns:
        dict with success flag and the effective switch.
    """
    if enabled and not internal and source in ("api", "shell"):
        try:
            from l3.tool_system.engineering_debug import get_engineering_debug

            get_engineering_debug().refresh(force=True)
            if not get_engineering_debug().is_enabled():
                return {
                    "success": False,
                    "error": "prompt monitor requires engineering debug mode",
                    "source": source,
                }
        except Exception:
            return {"success": False, "error": "engineering debug state unavailable", "source": source}
    with _lock:
        if enabled is not None:
            _state["enabled"] = bool(enabled)
            if enabled:
                # Enabling installs the usage hook so get_prompt_monitored
                # counts hits in production paths (engineering/debug mode).
                install_prompt_hook()
        return {"success": True, "source": source, **prompt_monitor_status()}


def reset_prompt_monitor() -> None:
    """Reset the monitor (switch + metrics) for tests / lifecycle."""
    with _lock:
        _state["enabled"] = PROMPT_MONITOR_ENABLED_DEFAULT
        _metrics.clear()


def record_prompt_usage(key: str) -> None:
    """Record one usage sample for a prompt key (bypass, never raises)."""
    if not key:
        return
    with _lock:
        if not _state["enabled"]:
            return
        entry = _metrics.setdefault(key, {"used": 0, "ok": 0, "fail": 0})
        entry["used"] += 1


def install_prompt_hook() -> bool:
    """Install this monitor's usage recorder on the L1 prompt hooks.

    L1 defines ``register_prompt_usage_hook``; the L3 monitor registers its
    recorder there so ``get_prompt_monitored`` counts hits without L1 ever
    importing upper layers (dependency direction stays L3 → L1).

    Returns:
        True when installed, False when the hook surface is unavailable.
    """
    try:
        from l1.kernel.prompts import register_prompt_usage_hook

        register_prompt_usage_hook(record_prompt_usage)
        return True
    except Exception as e:
        logger.debug("prompt_monitor: hook install skipped: %s", e)
        return False


def record_prompt_outcome(key: str, success: bool) -> None:
    """Record a success/failure sample for a prompt key (card/task outcome)."""
    if not key:
        return
    with _lock:
        if not _state["enabled"]:
            return
        entry = _metrics.setdefault(key, {"used": 0, "ok": 0, "fail": 0})
        if success:
            entry["ok"] += 1
        else:
            entry["fail"] += 1


def prompt_monitor_stats() -> dict:
    """Quantified analysis: frequency + success/failure rates per prompt key.

    Returns:
        dict with per-key metrics (used / ok / fail / success_rate) and a
        global summary (total usage, avg success rate).
    """
    with _lock:
        snap = {k: dict(v) for k, v in sorted(_metrics.items())}
    out: dict[str, dict[str, float | int]] = {}
    total_used = 0
    total_ok = 0
    for key, m in snap.items():
        used = m.get("used", 0)
        ok = m.get("ok", 0)
        fail = m.get("fail", 0)
        total_used += used
        total_ok += ok
        out[key] = {
            "used": used,
            "ok": ok,
            "fail": fail,
            "success_rate": round(ok / used, 3) if used else 0.0,
        }
    return {
        "success": True,
        "tracked_keys": len(out),
        "total_usage": total_used,
        "avg_success_rate": round(total_ok / total_used, 3) if total_used else 0.0,
        "per_prompt": out,
    }


def _prompt_records(limit: int = 0) -> list:
    """Return recent prompt_metrics RC records for RecordCenter query/export.

    P2-3: the RC ``prompt_metrics`` events are the durable store; RecordCenter
    folds them into unified query/export via the registered ``prompt`` source.
    """
    try:
        from l3.bus.reference_channel import get_rc

        return list(get_rc().export(event_type="prompt_metrics", limit=limit))
    except Exception:
        return []


def register_prompt_source() -> dict:
    """Register the ``prompt`` record source with the RecordCenter (idempotent).

    Makes RecordCenter stats()/export()/query() cover the prompt monitor:
    stats_fn reports the live per-key aggregates, query/export_fn recall the
    RC prompt_metrics trail. Best-effort, never raises.

    Returns:
        dict with success flag.
    """
    try:
        from l3.services.record_center import get_record_center

        get_record_center().register_source(
            "prompt",
            query_fn=_prompt_records,
            stats_fn=prompt_monitor_stats,
            export_fn=_prompt_records,
        )
        return {"success": True}
    except Exception as e:
        logger.debug("prompt_monitor: record source register skipped: %s", e)
        return {"success": False, "error": str(e)}


def emit_prompt_metrics() -> dict:
    """Emit the current metrics snapshot to the reference channel (RC).

    Correlation input for prompt optimization: the RC event
    ``prompt_metrics`` carries the per-key usage/success/failure aggregates
    so the causal audit trail links prompt quality with card outcomes.

    Returns:
        dict with success flag and the emitted sample count (0 when the
        monitor is disabled).
    """
    with _lock:
        enabled = bool(_state["enabled"])
        snap = {k: dict(v) for k, v in _metrics.items()}
    if not enabled or not snap:
        return {"success": True, "emitted": 0}
    try:
        from l3.bus.reference_channel import get_rc

        rc = get_rc()
        for key, m in snap.items():
            rc.event("prompt_metrics", {"prompt_key": key, **m}, source="prompt_monitor")
        rc.flush()
        return {"success": True, "emitted": len(snap)}
    except Exception as e:
        logger.debug("prompt_monitor: RC emit skipped: %s", e)
        return {"success": False, "emitted": 0, "error": str(e)}
