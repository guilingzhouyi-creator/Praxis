"""Tests for the generalization verify gate (P1-④)."""

from __future__ import annotations

import importlib


def _fresh_lifecycle():
    """Build a bare lifecycle mixin instance for gate testing."""
    import l3.memory.r4_skill_lifecycle as lc

    importlib.reload(lc)
    return lc.SkillLifecycleMixin()


def test_verify_gate_promotes_on_success_signals():
    """P1-④: cumulative success signals promote candidate → active."""
    from l1.kernel.skill import get_skill_manager, reset_skill_manager

    reset_skill_manager()
    try:
        sm = get_skill_manager()
        sm.create(
            "lean_read_file_lessons",
            description="d",
            prompt="p",
            rules=[{"rule": "check perms", "preferred": 0.8, "verified": 0, "hit": 0}],
            allowed_tools=["read_file"],
            layer="exec",
            internal=True,
        )
        lc = _fresh_lifecycle()
        for _ in range(3):
            lc.record_card_skill_signal(["lean_read_file_lessons"], success=True)
        rec = sm.get("lean_read_file_lessons")
        assert rec.get("status") == "active"
    finally:
        reset_skill_manager()


def test_verify_gate_rolls_back_on_failure_signals():
    """P1-④: cumulative failure signals roll back candidate → deprecated."""
    from l1.kernel.skill import get_skill_manager, reset_skill_manager

    reset_skill_manager()
    try:
        sm = get_skill_manager()
        sm.create(
            "lean_write_file_lessons",
            description="d",
            prompt="p",
            rules=[{"rule": "avoid overwrite", "preferred": 0.8, "verified": 0, "hit": 0}],
            allowed_tools=["write_file"],
            layer="exec",
            internal=True,
        )
        lc = _fresh_lifecycle()
        for _ in range(5):
            lc.record_card_skill_signal(["lean_write_file_lessons"], success=False)
        rec = sm.get("lean_write_file_lessons")
        assert rec.get("status") == "deprecated"
    finally:
        reset_skill_manager()


def test_verify_gate_noop_below_threshold():
    """P1-④: below thresholds the skill stays a candidate (no status)."""
    from l1.kernel.skill import get_skill_manager, reset_skill_manager

    reset_skill_manager()
    try:
        sm = get_skill_manager()
        sm.create(
            "lean_ls_lessons",
            description="d",
            prompt="p",
            rules=[{"rule": "use -la", "preferred": 0.8, "verified": 0, "hit": 0}],
            allowed_tools=["ls"],
            layer="exec",
            internal=True,
        )
        lc = _fresh_lifecycle()
        lc.record_card_skill_signal(["lean_ls_lessons"], success=True)
        rec = sm.get("lean_ls_lessons")
        assert rec.get("status", "") == ""
    finally:
        reset_skill_manager()
