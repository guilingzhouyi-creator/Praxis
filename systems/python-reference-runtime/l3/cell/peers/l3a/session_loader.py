"""Decision-layer context loader — dynamic strategy engine (3.3, P2-②).

Determines how much conversation context to load into a visualization
window (pagination + label-alternated dispatch + cache hits). It does NOT
decide the volume injected into the L3A session itself — the loader feeds
the front-end window; the first follow-up user message triggers the actual
context send to the provider.

Strategy:
  - Pagination: load ``page`` of ``page_size`` entries (recent-first).
  - Label alternation: user / assistant entries are dispatched alternately
    (upper user tag → lower answer tag), so the window preserves the
    1:1 conversation shape.
  - Cache hits: already-sent entry seqs are tracked; a repeat request for
    the same seq returns a cache-hit marker instead of re-sending the
    content (bandwidth / latency savings).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _entries(session_id: str) -> list[dict]:
    """Load a session's conversation entries (sorted by seq)."""
    try:
        from l3.cell.peers.l3a.session_json import load_conversation

        data = load_conversation(session_id) or {}
        return sorted(data.get("entries", []), key=lambda e: int(e.get("seq", 0)))
    except Exception as e:
        logger.debug("session_loader: load failed: %s", e)
        return []


def dynamic_loader(
    session_id: str,
    page: int = 0,
    page_size: int = 10,
    sent_seqs: set[int] | None = None,
) -> dict:
    """Load a page of conversation entries with cache-hit awareness.

    Args:
        session_id: the session whose conversation is loaded.
        page: zero-based page index (recent-first window).
        page_size: entries per page.
        sent_seqs: seqs already sent to the window (cache); hits are
            marked ``cached=True`` and their content is omitted.

    Returns:
        dict with the window entries (label-alternated), a next-cursor,
        and cache-hit stats.
    """
    all_entries = _entries(session_id)
    total = len(all_entries)
    start = max(0, total - (page + 1) * page_size)
    end = max(0, total - page * page_size)
    window = all_entries[start:end]
    sent = set(sent_seqs or [])
    dispatched: list[dict] = []
    hits = 0
    for e in window:
        seq = int(e.get("seq", 0))
        if seq in sent:
            hits += 1
            dispatched.append({"seq": seq, "cached": True, "user": "", "assistant": ""})
            continue
        # Label-alternated dispatch: upper user tag → lower answer tag.
        dispatched.append(
            {
                "seq": seq,
                "cached": False,
                "user": {
                    "tag": (e.get("user") or {}).get("tag", "user"),
                    "content": (e.get("user") or {}).get("content", ""),
                },
                "assistant": {
                    "tag": (e.get("assistant") or {}).get("tag", "assistant"),
                    "content": (e.get("assistant") or {}).get("content", ""),
                },
            }
        )
    return {
        "success": True,
        "session_id": session_id,
        "page": page,
        "page_size": page_size,
        "total": total,
        "dispatched": len(dispatched),
        "cache_hits": hits,
        "next_cursor": page + 1 if end > 0 else None,
        "entries": dispatched,
    }


def load_for_window(session_id: str, page: int = 0, page_size: int = 10) -> dict:
    """Load a window page for the front-end visualization (no cache)."""
    return dynamic_loader(session_id, page=page, page_size=page_size, sent_seqs=None)
