"""Memory context builder — extracted from memory.py for modularity.

Contains MemoryManager.build_context() logic.
"""

from __future__ import annotations

import logging
import time

from l1.kernel.params.system import CONTEXT_BUILD_MAX_TOKENS, LOG_TRUNC_300

logger = logging.getLogger(__name__)


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

    w = mem.working.summarize(agent_id)
    if w:
        tok = _estimate_tokens(w)
        if tok <= remaining:
            parts.append("=== Working Memory ===\n" + w)
            remaining -= tok

    s = mem.short.summarize(agent_id)
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
        l_text = "\n".join(f"[{e.entry_type}] {e.content[:LOG_TRUNC_300]}" for e in l_entries)
        tok = _estimate_tokens(l_text)
        if tok <= remaining:
            parts.append("=== Knowledge ===\n" + l_text)

    return "\n\n".join(parts)
