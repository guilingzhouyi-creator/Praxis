"""Unit tests for contribution scoring precision (Wilson + decay + dimensions).

Covers the R4Agent curation score upgrades: the Wilson lower bound replaces
the raw useful/injected ratio, time decay discounts stale wins, and
per-dimension sub-scores split by tool/card nature.
"""

from __future__ import annotations

from l1.kernel.params.agent import R4_CONTRIB_DECAY_HALF_LIFE
from l3.memory.r4_skill_lifecycle import _decay_weight, _wilson_lower_bound


def test_wilson_bounds_small_samples():
    """A single observation must not flip the verdict (bound stays low)."""
    assert _wilson_lower_bound(0, 0) == 0.0
    assert _wilson_lower_bound(1, 1) < 0.5  # one success: not enough evidence
    assert _wilson_lower_bound(0, 1) == 0.0
    assert _wilson_lower_bound(1, 10) < _wilson_lower_bound(9, 10)
    # Perfect score with many samples approaches 1 but never exceeds it.
    assert _wilson_lower_bound(1000, 1000) > 0.99


def test_wilson_converges_to_ratio():
    """With enough trials the bound converges toward the true ratio."""
    for ratio in (0.1, 0.3, 0.5, 0.8):
        bound = _wilson_lower_bound(int(ratio * 10000), 10000)
        assert abs(bound - ratio) < 0.02, f"ratio={ratio} bound={bound}"


def test_wilson_tighter_with_more_samples():
    """More samples ⇒ narrower interval ⇒ bound closer to the ratio."""
    spread_small = abs(_wilson_lower_bound(50, 100) - 0.5)
    spread_large = abs(_wilson_lower_bound(500, 1000) - 0.5)
    assert spread_large < spread_small


def test_decay_weight_half_life():
    """A win halves its weight exactly at the half-life."""
    assert _decay_weight(0) == 1.0
    assert abs(_decay_weight(R4_CONTRIB_DECAY_HALF_LIFE) - 0.5) < 1e-9
    assert abs(_decay_weight(2 * R4_CONTRIB_DECAY_HALF_LIFE) - 0.25) < 1e-9
    assert _decay_weight(-5) == 1.0


def test_dimension_bump_and_sub_scores():
    """bump_usage(dimension=...) records sub-counters consumed by curation."""
    from l1.kernel.skill import get_skill_manager

    sm = get_skill_manager()
    created = sm.create(
        "contrib-dim-test",
        description="Use when testing dimension sub-scores",
        prompt="body",
        tags=["evolved"],
        agent_id="dev",
        role="l3",
    )
    assert created.get("success"), created
    for _ in range(6):
        sm.bump_usage("contrib-dim-test", dimension="tool:read_file")
    sm.bump_usage("contrib-dim-test", dimension="tool:write_file")
    rec = sm.get("contrib-dim-test")
    dims = rec.get("usage_by_dimension", {})
    assert dims.get("tool:read_file") == 6
    assert dims.get("tool:write_file") == 1
    # The curation pass computes sub-scores from the dimension counters.
    from l3.memory.r4_skill_lifecycle import SkillLifecycleMixin

    mixin = SkillLifecycleMixin()
    sub = mixin._dimension_sub_scores(rec)
    assert "tool:read_file" in sub
    # write_file has 1 trial < R4_CONTRIB_SUB_MIN_TRIALS → excluded.
    assert "tool:write_file" not in sub
    assert 0.0 <= sub["tool:read_file"] <= 1.0
    sm.delete("contrib-dim-test", agent_id="dev", role="l3")
