"""Tool-result offload cache — structured per-Cell unloading of large results.

Peer agents are highly structured card-execution entities: when a tool
result exceeds the folding budget, it is NOT merely head+tail truncated in
the context trail — the full result is offloaded to the per-Cell cache
(tiered-cache L1, key ``cell:{cell_id}::tool:{call_id}``) as a structured
record (tool_name + call_id + full payload + digest), and the trail keeps
only a recoverable reference line. This raises the compression ratio while
keeping the payload fetchable on demand.

Operator switches (API ``/api/v2/memory/tool-result`` + L2 ``/memory
tool-result``):
  enabled   — master switch (default off = legacy truncation behavior)
  max_chars — payload size above which offload applies

Degrades gracefully: disabled / unavailable cache / missing entry all
return empty results and never raise.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from l1.kernel.params.system import (
    TOOL_RESULT_OFFLOAD_ENABLED_DEFAULT,
    TOOL_RESULT_OFFLOAD_MAX_CHARS_DEFAULT,
)

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {
    "enabled": TOOL_RESULT_OFFLOAD_ENABLED_DEFAULT,
    "max_chars": TOOL_RESULT_OFFLOAD_MAX_CHARS_DEFAULT,
}
_lock = threading.RLock()


def tool_result_status() -> dict:
    """Return the offload-cache switch state."""
    with _lock:
        return {"enabled": bool(_state["enabled"]), "max_chars": int(_state["max_chars"])}


def set_tool_result_switches(enabled: bool | None = None, max_chars: int | None = None) -> dict:
    """Set the tool-result offload operator switches.

    Args:
        enabled: master switch (None = keep current).
        max_chars: payload size above which offload applies (None = keep).

    Returns:
        dict with success flag and the effective switches.
    """
    with _lock:
        if enabled is not None:
            _state["enabled"] = bool(enabled)
        if max_chars is not None:
            _state["max_chars"] = max(512, int(max_chars))
        return {"success": True, **tool_result_status()}


def reset_tool_result() -> None:
    """Reset the offload-cache switches (tests / lifecycle)."""
    with _lock:
        _state["enabled"] = TOOL_RESULT_OFFLOAD_ENABLED_DEFAULT
        _state["max_chars"] = TOOL_RESULT_OFFLOAD_MAX_CHARS_DEFAULT


def _key(cell_id: str, call_id: str) -> str:
    return f"cell:{cell_id}::tool:{call_id}"


def offload_result(cell_id: str, call_id: str, tool_name: str, result: dict) -> bool:
    """Offload a large structured tool result to the per-Cell cache.

    Args:
        cell_id: producing Cell (cache scope).
        call_id: pipeline call id (recoverable reference).
        tool_name: the tool that produced the result.
        result: the structured result payload (folded before caching when
            the digest switch is on; the full dict is stored otherwise).

    Returns:
        True when the result was offloaded, False when disabled / skipped.
    """
    with _lock:
        enabled = bool(_state["enabled"])
    if not enabled:
        return False
    try:
        from l3.memory.tiered_cache import get_tiered_cache

        get_tiered_cache().set("L1", _key(cell_id, call_id), {"tool": tool_name, "result": result})
        return True
    except Exception as e:
        logger.debug("tool_result_cache: offload skipped: %s", e)
        return False


def fetch_result(cell_id: str, call_id: str) -> dict:
    """Recover an offloaded tool result ({} when absent/disabled)."""
    with _lock:
        enabled = bool(_state["enabled"])
    if not enabled:
        return {}
    try:
        from l3.memory.tiered_cache import get_tiered_cache

        value = get_tiered_cache().get("L1", _key(cell_id, call_id))
        return value or {}
    except Exception as e:
        logger.debug("tool_result_cache: fetch skipped: %s", e)
        return {}


def reclaim(cell_id: str = "") -> int:
    """Explicitly evict expired offloaded results (per-Cell or global).

    The tiered-cache ``get`` path already drops expired entries lazily
    (physical delete); this sweep matches Cell shutdown / on-demand cleanup
    semantics (same pattern as ``run_code_cache.reclaim``). Returns the
    number of expired entries reclaimed.

    Args:
        cell_id: when given, only this Cell's offloaded results are swept
            (keys ``cell:{cell_id}::tool:*``); empty sweeps all.

    Returns:
        Count of expired entries dropped.
    """
    try:
        from l3.memory.tiered_cache import get_tiered_cache

        cache = get_tiered_cache()
        evicted = 0
        prefix = _key(cell_id, "") if cell_id else "cell:"
        for key in cache.keys("L1"):
            if key.startswith(prefix) and "::tool:" in key and cache.get("L1", key) is None:
                # get() lazily drops expired entries; a None after a
                # key-scan hit means the entry expired and was reclaimed.
                evicted += 1
        return evicted
    except Exception as e:
        logger.debug("tool_result_cache: reclaim failed: %s", e)
        return 0


def maybe_offload(cell_id: str, call_id: str, tool_name: str, result: dict) -> dict:
    """Offload when the payload exceeds the budget; returns the trail entry.

    Args:
        cell_id / call_id / tool_name / result: as in ``offload_result``.

    Returns:
        A context-trail entry: the offload reference (with digest) when
        offloaded, else the original result unchanged.
    """
    with _lock:
        max_chars = int(_state["max_chars"])
    try:
        size = len(str(result))
    except Exception:
        size = 0
    if size > max_chars and offload_result(cell_id, call_id, tool_name, result):
        digest = str(result)[:max_chars]
        return {
            "offloaded": True,
            "tool": tool_name,
            "call_id": call_id,
            "digest": digest + ("…" if len(str(result)) > max_chars else ""),
        }
    return result
