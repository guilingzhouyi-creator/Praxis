"""Memory context builder — extracted from memory.py for modularity.

Contains MemoryManager.build_context() logic.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time

from l1.kernel.params.system import (
    CONTEXT_BUILD_MAX_TOKENS,
    LOG_TRUNC_300,
    MEMORY_INJECT_DEDUP_ENABLED_DEFAULT,
)

logger = logging.getLogger(__name__)

# ── Injection dedup state (operator switch via API + L2 Shell) ──
_dedup_state: dict = {"enabled": MEMORY_INJECT_DEDUP_ENABLED_DEFAULT}
_dedup_lock = threading.RLock()


def inject_dedup_status() -> dict:
    """Return the injection-dedup switch state."""
    with _dedup_lock:
        return {"enabled": bool(_dedup_state["enabled"])}


def set_inject_dedup(enabled: bool | None = None) -> dict:
    """Set the injection-dedup master switch.

    Args:
        enabled: None keeps the current state.

    Returns:
        dict with success flag and the effective switch.
    """
    with _dedup_lock:
        if enabled is not None:
            _dedup_state["enabled"] = bool(enabled)
    return {"success": True, **inject_dedup_status()}


def reset_inject_dedup() -> None:
    """Reset the injection-dedup switch (tests / lifecycle)."""
    with _dedup_lock:
        _dedup_state["enabled"] = MEMORY_INJECT_DEDUP_ENABLED_DEFAULT


def _dedup_lines(text: str) -> str:
    """Drop repeated content lines from an injection block (fingerprint dedup).

    Line-level MD5 fingerprint: the first occurrence of a non-empty,
    non-watermark line is kept; later duplicates are dropped. Watermark
    lines (<!-- ... -->) are never treated as duplicates of each other.
    """
    if not text:
        return ""
    seen: set[str] = set()
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if stripped.startswith("<!--") or stripped.endswith("-->"):
            kept.append(line)
            continue
        fp = hashlib.md5(stripped.encode("utf-8", errors="replace")).hexdigest()
        if fp in seen:
            continue
        seen.add(fp)
        kept.append(line)
    return "\n".join(kept)


def _dedup_block(text: str) -> str:
    """Apply dedup under the operator switch; degrades to the input unchanged."""
    with _dedup_lock:
        enabled = bool(_dedup_state["enabled"])
    if not enabled:
        return text
    try:
        return _dedup_lines(text)
    except Exception:
        return text


def build_context(
    mem,
    agent_id: str,
    max_tokens: int = CONTEXT_BUILD_MAX_TOKENS,
    intent: str = "",
    domain: str = "",
) -> str:
    """Build an LLM context string from all rings, token-budgeted.

    Context watermarks are injected for traceability.
    ``intent``/``domain`` carry the driving card's identity-hit: when the
    fine-grained memory gate is enabled, the knowledge block is filtered to
    entries the hit identity may see.
    """
    from l3.memory.memory_ring import _estimate_tokens

    parts = []
    remaining = max_tokens

    _ctx_id = f"ctx-{int(time.time() * 1000):x}"
    _watermark = f"<!-- WATERMARK: id={_ctx_id} agent={agent_id} budget={max_tokens} -->"
    parts.append(_watermark)
    remaining -= len(_watermark)

    w = _dedup_block(mem.working.summarize(agent_id))
    if w:
        tok = _estimate_tokens(w)
        if tok <= remaining:
            parts.append("=== Working Memory ===\n" + w)
            remaining -= tok

    s = _dedup_block(mem.short.summarize(agent_id))
    if s:
        tok = _estimate_tokens(s)
        if tok <= remaining:
            parts.append("=== Recent History ===\n" + s)
            remaining -= tok

    from l1.kernel.params.system import MEMORY_BUILD_CONTEXT_LIMIT

    l_entries = mem.long.query(agent_id=agent_id, limit=MEMORY_BUILD_CONTEXT_LIMIT)
    # Identity gate over the knowledge block: the fine-grained filter
    # follows the driving card's identity-hit (intent/domain). Disabled or
    # unset → entries pass through unchanged (backward compatible).
    if l_entries and (intent or domain):
        try:
            from l3.memory.memory_domain_filter import get_memory_filter

            _filt = get_memory_filter()
            if _filt.status().get("enabled"):
                l_entries = [
                    e
                    for e in l_entries
                    if _filt.is_allowed(e.to_dict(), cell_id="", role="", scope="", intent=intent, domain=domain)
                ]
        except Exception:
            logger.debug("memory_context: identity gate skipped")
    if l_entries:
        l_text = _dedup_block("\n".join(f"[{e.entry_type}] {e.content[:LOG_TRUNC_300]}" for e in l_entries))
        tok = _estimate_tokens(l_text)
        if tok <= remaining:
            parts.append("=== Knowledge ===\n" + l_text)

    return "\n\n".join(parts)
