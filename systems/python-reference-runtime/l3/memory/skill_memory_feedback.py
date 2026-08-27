"""Skill→memory feedback (P1-③) — batched skill-usage writes to R3.

Every skill usage (bump_usage / bump_usage_for_tools) notifies the L1
usage hooks; this module batches those events and flushes them into R3
memory as ``skill_usage`` entries (entry_type=skill_usage), so the
generalization loop has a reverse path: skill experience → memory.

Performance: events are AGGREGATED in a queue and flushed in one batch
(per-call counter / time threshold), so a hot tool loop never performs a
memory write per event. The hook install is idempotent and the whole
path is a bypass — a failing flush never affects the usage bump.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

_lock = threading.RLock()
# skill name -> usage count pending flush
_pending: dict[str, int] = {}
# Total pending events (O(1) threshold check — no per-event sum, P1-③).
_total_pending: int = 0
_last_flush: float = 0.0
_installed: bool = False

_BATCH_SIZE = 8  # flush when pending events reach this
_FLUSH_INTERVAL = 60.0  # or when this many seconds elapsed


def _flush() -> int:
    """Flush the pending skill-usage events into R3 memory (one batch)."""
    global _pending, _total_pending, _last_flush
    with _lock:
        batch = dict(_pending)
        _pending = {}
        _total_pending = 0
        _last_flush = time.time()
    if not batch:
        return 0
    try:
        from l3.memory.central_memory import get_memory

        mem = get_memory("skill_feedback")
        written = 0
        for skill_name, count in batch.items():
            try:
                mem.remember(
                    agent_id="skill_feedback",
                    entry_type="skill_usage",
                    content=f"[skill:{skill_name}] usage_x{count}",
                    tags=["skill", "usage", skill_name],
                    importance=0.4,
                    ring=3,
                )
                written += 1
            except Exception:
                logger.debug("skill_memory_feedback: remember failed: %s", skill_name)
        return written
    except Exception as e:
        logger.debug("skill_memory_feedback: flush failed: %s", e)
        return 0


def _on_usage(skill_name: str) -> None:
    """Usage hook: aggregate the event, flush when threshold/interval hit."""
    global _pending, _total_pending, _last_flush
    with _lock:
        _pending[skill_name] = _pending.get(skill_name, 0) + 1
        _total_pending += 1
        # O(1) threshold via the running total — no per-event sum (P1-③).
        due = _total_pending >= _BATCH_SIZE or (time.time() - _last_flush >= _FLUSH_INTERVAL)
    if due:
        _flush()


def install_feedback_hook() -> bool:
    """Install the batcher on the L1 skill-usage hooks (idempotent)."""
    global _installed
    if _installed:
        return True
    try:
        from l1.kernel.skill import register_usage_feedback_hook

        register_usage_feedback_hook(_on_usage)
        _installed = True
        return True
    except Exception as e:
        logger.debug("skill_memory_feedback: hook install failed: %s", e)
        return False


def feedback_pending() -> int:
    """Pending un-flushed usage events (O(1) via the running total)."""
    with _lock:
        return _total_pending


def reset_feedback() -> None:
    """Reset the queue + installed flag (tests / lifecycle)."""
    global _pending, _total_pending, _installed, _last_flush
    with _lock:
        _pending = {}
        _total_pending = 0
        _installed = False
        # Anchor the flush clock to now so a fresh reset never triggers an
        # immediate time-based flush on the very first usage event.
        _last_flush = time.time()
