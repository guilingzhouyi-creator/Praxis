"""2.1-D6 tests — card completion → structured build + review results."""

from __future__ import annotations

import pytest

from l3.memory.tiered_cache import get_tiered_cache, reset_tiered_cache
from l3.services.card_tool_stats import _on_card_completed, reset_card_tool_stats
from l3.services.review_pipeline import get_review_pipeline, reset_review_pipeline


@pytest.fixture(autouse=True)
def _clean():
    reset_card_tool_stats()
    reset_tiered_cache()
    reset_review_pipeline()
    yield
    reset_card_tool_stats()
    reset_tiered_cache()
    reset_review_pipeline()


def test_card_completion_aggregates_build_and_review():
    """Completing a card writes build_result + review_result sections."""
    tc = get_tiered_cache()
    tc.set_shared_summary("card-1", "build_summary", {"changed_lines": 12, "hunks": 2})

    _on_card_completed("card-1", "completed", {"agent_id": "agent-a", "path": "systems/python-reference-runtime/a.py"})

    from l1.kernel.registry import get_registry

    section = get_registry().get_section("card_build_review")
    assert section is not None
    assert section["card_id"] == "card-1"
    assert section["build_result"]["changed_lines"] == 12
    assert section["build_result"]["hunks"] == 2
    assert section["review_result"]["disposition"] == "small"  # 12 <= 50 threshold
    assert section["review_result"]["fixed"] is True


def test_card_completion_large_change_routes_to_rework():
    """Large build results route the review to rework."""
    tc = get_tiered_cache()
    tc.set_shared_summary("card-2", "build_summary", {"changed_lines": 500, "hunks": 20})

    _on_card_completed("card-2", "completed", {"agent_id": "agent-a"})

    from l1.kernel.registry import get_registry

    section = get_registry().get_section("card_build_review")
    assert section["review_result"]["disposition"] == "large"
    assert section["review_result"]["rework"] is True


def test_card_completion_without_build_summary_degrades():
    """No build summary → zeroed build result, no crash."""
    _on_card_completed("card-3", "failed", {"agent_id": "agent-a"})
    from l1.kernel.registry import get_registry

    section = get_registry().get_section("card_build_review")
    assert section["build_result"]["changed_lines"] == 0
    assert section["build_result"]["hunks"] == 0


def test_threshold_adjust_affects_review_disposition():
    """Lowering the threshold flips a previously-small change to large."""
    pipe = get_review_pipeline()
    pipe.set_threshold(10)
    tc = get_tiered_cache()
    tc.set_shared_summary("card-4", "build_summary", {"changed_lines": 12, "hunks": 1})

    _on_card_completed("card-4", "completed", {})
    from l1.kernel.registry import get_registry

    section = get_registry().get_section("card_build_review")
    assert section["review_result"]["disposition"] == "large"
