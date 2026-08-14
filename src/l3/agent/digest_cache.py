"""Conversation digest cache — card-indexed summary buffer for agent loops.

When a conversation's middle messages are folded (see
``AgentLoop._truncate_trail``), the elided span is NOT dropped: it is
condensed into a character-capped digest and written to the per-Cell
digest buffer (the tiered-cache L2 shared-summary layer, key
``{cell_id}::{card_id}::digest``). A later resume / cross-agent read can
recover the span's gist from the buffer instead of the raw messages,
improving the compression ratio while keeping information recoverable.

Operator switches (API ``/api/v2/memory/digest`` + L2 ``/memory digest``):
  enabled       — master switch (default off = folding drops the span)
  max_chars     — per-digest character cap (default DIGEST_MAX_CHARS_DEFAULT)

Degrades gracefully: a disabled cache, an unavailable tiered cache, or a
missing entry all return empty results and never raise.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from l1.kernel.params.system import (
    DIGEST_ENABLED_DEFAULT,
    DIGEST_MAX_CHARS_DEFAULT,
    LOG_TRUNC_120,
)

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {"enabled": DIGEST_ENABLED_DEFAULT, "max_chars": DIGEST_MAX_CHARS_DEFAULT}
_lock = threading.RLock()

_DIGEST_SUFFIX = "::digest"


def digest_status() -> dict:
    """Return the digest-cache switch state."""
    with _lock:
        return {"enabled": bool(_state["enabled"]), "max_chars": int(_state["max_chars"])}


def set_digest_switches(enabled: bool | None = None, max_chars: int | None = None) -> dict:
    """Set the digest-cache operator switches.

    Args:
        enabled: master switch (None = keep current).
        max_chars: per-digest character cap (None = keep current).

    Returns:
        dict with success flag and the effective switches.
    """
    with _lock:
        if enabled is not None:
            _state["enabled"] = bool(enabled)
        if max_chars is not None:
            _state["max_chars"] = max(64, int(max_chars))
        return {"success": True, **digest_status()}


def reset_digest() -> None:
    """Reset the digest-cache switches (tests / lifecycle)."""
    with _lock:
        _state["enabled"] = DIGEST_ENABLED_DEFAULT
        _state["max_chars"] = DIGEST_MAX_CHARS_DEFAULT


def _cap(text: str, limit: int) -> str:
    """Truncate text to a char budget with an ellipsis marker."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[{len(text) - limit} chars elided]"


def fold_messages(cell_id: str, card_id: str, messages: list[dict]) -> str:
    """Condense an elided message span into one capped digest and cache it.

    Args:
        cell_id: the producing Cell (digest buffer scope).
        card_id: the driving card index (front/back card index).
        messages: the elided conversation span (role/content dicts).

    Returns:
        The digest text (capped); the raw span is replaced by this line in
        the caller's context trail. Empty when the cache is disabled.
    """
    with _lock:
        enabled = bool(_state["enabled"])
        max_chars = int(_state["max_chars"])
    if not enabled:
        return ""
    user_lines = [str(m.get("content", ""))[:LOG_TRUNC_120] for m in messages if m.get("role") == "user"]
    digest = (
        "[FOLDED] " + "; ".join(user_lines[:5]) + (f" (+{len(user_lines) - 5} more)" if len(user_lines) > 5 else "")
    )
    capped = _cap(digest, max_chars)
    try:
        from l3.memory.tiered_cache import get_tiered_cache

        get_tiered_cache().set_shared_summary(cell_id, f"{card_id}{_DIGEST_SUFFIX}", capped)
    except Exception as e:
        logger.debug("digest_cache: buffer write skipped: %s", e)
    return capped


def get_digest(cell_id: str, card_id: str) -> str:
    """Recover a folded span's digest from the buffer ("" when absent)."""
    with _lock:
        enabled = bool(_state["enabled"])
    if not enabled:
        return ""
    try:
        from l3.memory.tiered_cache import get_tiered_cache

        value = get_tiered_cache().get_shared_summary(cell_id, f"{card_id}{_DIGEST_SUFFIX}")
        return str(value or "")
    except Exception as e:
        logger.debug("digest_cache: buffer read skipped: %s", e)
        return ""


def reclaim(cell_id: str = "") -> int:
    """Explicitly evict digests (per-Cell or global).

    Used at Cell teardown / on demand: drops this Cell's digests from the
    tiered-cache L2 shared-summary layer (physical delete via invalidate)
    so the folded-span summaries live and die with the Cell. Counts the
    entries dropped.

    Args:
        cell_id: when given, only this Cell's digests are swept
            (keys ``{cell_id}::*::digest``); empty sweeps all.

    Returns:
        Count of entries dropped.
    """
    evicted = 0
    try:
        from l3.memory.tiered_cache import get_tiered_cache

        cache = get_tiered_cache()
        prefix = f"{cell_id}::" if cell_id else ""
        for key in cache.keys("L2"):
            if key.startswith(prefix) and key.endswith(_DIGEST_SUFFIX):
                cache.invalidate("L2", key)
                evicted += 1
        return evicted
    except Exception as e:
        logger.debug("digest_cache: reclaim failed: %s", e)
        return evicted
