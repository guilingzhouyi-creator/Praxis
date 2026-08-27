"""2.1-D3 tests — review pipeline bypass monitor (small → fix, large → rework)."""

from __future__ import annotations

import pytest

from l3.services.review_pipeline import get_review_pipeline, reset_review_pipeline


@pytest.fixture(autouse=True)
def _clean():
    reset_review_pipeline()
    yield
    reset_review_pipeline()


def _review_diff(changed_lines: int) -> dict:
    return {"stats": {"changed_lines": changed_lines}}


def test_small_change_fixed_in_place():
    """Small changes are fixed in place by the review department."""
    pipe = get_review_pipeline()
    r = pipe.dispose(_review_diff(10), rel_path="systems/python-reference-runtime/a.py", agent_id="agent-a")
    assert r["disposition"] == "small"
    assert r["fixed"] is True
    assert r["rework"] is False


def test_large_change_routes_to_rework():
    """Large changes route back through the Cell-to-Cell channel + L3A report."""
    pipe = get_review_pipeline()
    r = pipe.dispose(_review_diff(500), rel_path="systems/python-reference-runtime/a.py", agent_id="agent-a")
    assert r["disposition"] == "large"
    assert r["fixed"] is False
    assert r["rework"] is True
    assert r["reported_to_l3a"] is True


def test_large_change_directed_channel_with_cell():
    """dispose(cell_id=...) routes the rework through the L3B topology."""
    from l3.bus.l3b_bus import get_bus, reset_bus

    reset_bus()
    bus = get_bus()
    bus.register("l3b-cell-1-cell-2")
    pipe = get_review_pipeline()
    try:
        r = pipe.dispose(
            _review_diff(500), rel_path="systems/python-reference-runtime/a.py", agent_id="agent-a", cell_id="cell-2"
        )
        assert r["disposition"] == "large"
        assert r["rework"] is True
        assert r["reported_to_l3a"] is True
        msgs = bus.read("l3b-cell-1-cell-2", limit=5)
        rework = [m for m in msgs if m["msg_type"] == "REVIEW_REWORK"]
        assert rework, "expected a REVIEW_REWORK message on the Cell channel"
        assert rework[0]["payload"].get("rel_path") == "systems/python-reference-runtime/a.py"
    finally:
        reset_bus()


def test_threshold_boundary():
    """Changed lines == threshold counts as small (<=)."""
    pipe = get_review_pipeline()
    pipe.set_threshold(50)
    r = pipe.dispose(_review_diff(50))
    assert r["disposition"] == "small"
    r2 = pipe.dispose(_review_diff(51))
    assert r2["disposition"] == "large"


def test_threshold_runtime_adjust():
    """API threshold adjustment takes effect immediately."""
    pipe = get_review_pipeline()
    pipe.set_threshold(100)
    assert pipe.threshold()["max_small_change_lines"] == 100
    assert pipe.dispose(_review_diff(80))["disposition"] == "small"
    pipe.set_threshold(10)
    assert pipe.dispose(_review_diff(80))["disposition"] == "large"


def test_disabled_pipeline_noop():
    """Disabled pipeline returns disposition=disabled, never auto-fixes."""
    pipe = get_review_pipeline()
    pipe.set_enabled(False)
    r = pipe.dispose(_review_diff(5))
    assert r["disposition"] == "disabled"


def test_invalid_threshold_rejected():
    """Thresholds below 1 are rejected."""
    pipe = get_review_pipeline()
    r = pipe.set_threshold(0)
    assert r["success"] is False


def test_zero_changed_lines_no_fix():
    """No actual changes → nothing to fix, disposition small."""
    pipe = get_review_pipeline()
    r = pipe.dispose(_review_diff(0))
    assert r["disposition"] == "small"
    assert r["fixed"] is False


def test_api_threshold_handler():
    """PUT /api/v2/review/threshold surfaces the runtime adjust."""
    from l4.api_handlers.api_handlers_security import review_threshold_set

    r = review_threshold_set({"max_small_lines": 25})
    assert r["success"] is True
    assert r["settings"]["max_small_change_lines"] == 25
    assert get_review_pipeline().threshold()["max_small_change_lines"] == 25


# ── 2.1 Phase 1: bypass-threshold header fast path (frame, no decompress) ──


def test_dispose_frame_header_large():
    """A frame with many hunks routes to rework via the plaintext header."""
    from l4.sandbox.diff_codec import encode_hunks

    hunks = [
        {
            "type": "insert",
            "original_start": 1 + i,
            "modified_start": 1 + i,
            "added_lines": [f"line {i}\n"],
            "removed_lines": [],
            "semantic": "structural",
        }
        for i in range(60)  # 60 hunks > default threshold (50 lines)
    ]
    frame = encode_hunks(hunks, frame_type=2)
    pipe = get_review_pipeline()
    # Stats claim a small change, but the header fast path overrides → large.
    r = pipe.dispose(_review_diff(5), rel_path="systems/python-reference-runtime/a.py", agent_id="agent-a", frame=frame)
    assert r["disposition"] == "large"
    assert r["rework"] is True


def test_dispose_frame_header_small():
    """A frame with few hunks keeps the stats-based small disposition."""
    from l4.sandbox.diff_codec import encode_hunks

    hunks = [
        {
            "type": "replace",
            "original_start": 1,
            "modified_start": 1,
            "added_lines": ["def foo():\n"],
            "removed_lines": ["def bar():\n"],
            "semantic": "logic_change",
        }
    ]
    frame = encode_hunks(hunks, frame_type=2)
    pipe = get_review_pipeline()
    r = pipe.dispose(_review_diff(2), rel_path="systems/python-reference-runtime/a.py", agent_id="agent-a", frame=frame)
    assert r["disposition"] == "small"
    assert r["rework"] is False


def test_dispose_frame_none_unchanged():
    """dispose without a frame keeps the legacy stats-only path."""
    pipe = get_review_pipeline()
    r = pipe.dispose(_review_diff(2), rel_path="systems/python-reference-runtime/a.py", agent_id="agent-a")
    assert r["disposition"] == "small"


# ── HTN-C identity-hit driven rework ──


def test_dispose_large_carries_hit_identity():
    """A large-change rework carries the HTN-C identity hit on the channel."""
    from l3.bus.l3b_bus import get_bus, reset_bus

    reset_bus()
    bus = get_bus()
    bus.register("l3b-cell-1-cell-2")
    pipe = get_review_pipeline()
    try:
        r = pipe.dispose(
            _review_diff(500),
            rel_path="systems/python-reference-runtime/a.py",
            agent_id="agent-a",
            cell_id="cell-2",
            intent="verify regression",
        )
        assert r["disposition"] == "large"
        assert r["hit_identity"] == "test"  # "verify" matches the test identity
        msgs = bus.read("l3b-cell-1-cell-2", limit=5)
        rework = [m for m in msgs if m["msg_type"] == "REVIEW_REWORK"]
        assert rework
        assert rework[0]["payload"].get("hit_identity") == "test"
    finally:
        reset_bus()


def test_dispose_hit_identity_empty_without_intent():
    """No driving intent → hit_identity stays empty (peer agents, no static role)."""
    pipe = get_review_pipeline()
    r = pipe.dispose(_review_diff(500), rel_path="systems/python-reference-runtime/a.py", agent_id="agent-a")
    assert r["disposition"] == "large"
    assert r["hit_identity"] == ""
