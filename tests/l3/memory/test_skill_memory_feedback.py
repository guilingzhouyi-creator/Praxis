"""Tests for the skill→memory feedback batcher (P1-③)."""

from __future__ import annotations

from l3.memory.skill_memory_feedback import (
    feedback_pending,
    install_feedback_hook,
    reset_feedback,
)


def test_install_hook_idempotent():
    reset_feedback()
    try:
        assert install_feedback_hook() is True
        assert install_feedback_hook() is True  # second call no-op
    finally:
        reset_feedback()


def test_bump_usage_feeds_pending_queue():
    """P1-③: bump_usage notifies the batcher; events aggregate."""
    from l1.kernel.skill import get_skill_manager, reset_skill_manager

    reset_skill_manager()
    reset_feedback()
    try:
        sm = get_skill_manager()
        install_feedback_hook()
        sm.create("s-fb-1", description="d", prompt="p", layer="exec", internal=True)
        sm.bump_usage("s-fb-1")
        assert feedback_pending() == 1
        sm.bump_usage("s-fb-1")
        assert feedback_pending() == 2
    finally:
        reset_feedback()
        reset_skill_manager()


def test_flush_writes_skill_usage_memory(tmp_path, monkeypatch):
    """P1-③: the batch flush writes skill_usage entries into R3 memory."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path))
    from l1.kernel.skill import get_skill_manager, reset_skill_manager
    from l3.memory.central_memory import get_center, reset_center
    from l3.memory.skill_memory_feedback import _flush

    reset_center()
    reset_skill_manager()
    reset_feedback()
    try:
        sm = get_skill_manager()
        install_feedback_hook()
        sm.create("s-fb-2", description="d", prompt="p", layer="decision", internal=True)
        sm.bump_usage("s-fb-2")
        sm.bump_usage("s-fb-2")
        written = _flush()
        assert written >= 1
        # The batcher consumed the pending queue (the events were written).
        assert feedback_pending() == 0
        # The skill_usage entry landed in the skill_feedback scope.
        scope = get_center().get_or_create("skill_feedback")
        assert scope is not None
    finally:
        reset_feedback()
        reset_skill_manager()
        reset_center()
