"""Tests for the tool→skill reverse linkage (three-table loop).

A successful tool call must bump usage on skills named after the tool
(SkillManager.bump_usage_for_tools), closing the tool→skill→card loop that
card_dispatch feeds from the card side.
"""

from __future__ import annotations

import l3.tool_system.tool_pipeline as tp
from l1.kernel.skill import get_skill_manager, reset_skill_manager
from l3.tool_system.tool_pipeline import get_pipeline, reset_pipeline


def _successful_executor(*_a, **_k):
    return {"success": True}


def _allow_all_pipeline():
    """Pipeline with permissive gates so a tool call succeeds."""
    p = get_pipeline()
    p.constitution = type("C", (), {"is_allowed": lambda self, *a, **k: {"allowed": True}})()
    tp.agent_can_access = lambda *a, **k: True
    tp._get_gatechain = lambda: type(
        "G", (), {"check": lambda self, *a, **k: {"allowed": True, "decision": "PASS", "steps": []}}
    )()
    return p


def test_successful_tool_bumps_matching_skill():
    reset_skill_manager()
    reset_pipeline()
    try:
        sm = get_skill_manager()
        sm.create(name="read_file", prompt="Read", description="Use when reading files", internal=True)
        before = sm.get("read_file").get("useful_count", 0)

        p = _allow_all_pipeline()
        r = p.execute("read_file", "tester", {"path": "x"}, _registry={}, _executor=_successful_executor)
        assert r.get("success") is True

        after = sm.get("read_file").get("useful_count", 0)
        assert after > before
    finally:
        reset_skill_manager()
        reset_pipeline()


def test_failed_tool_does_not_bump_skill():
    reset_skill_manager()
    reset_pipeline()
    try:
        sm = get_skill_manager()
        sm.create(name="read_file", prompt="Read", description="Use when reading files", internal=True)
        before = sm.get("read_file").get("useful_count", 0)

        p = _allow_all_pipeline()
        r = p.execute("read_file", "tester", {"path": "x"}, _registry={}, _executor=lambda *a, **k: {"success": False})
        assert r.get("success") is False

        after = sm.get("read_file").get("useful_count", 0)
        assert after == before
    finally:
        reset_skill_manager()
        reset_pipeline()
