"""2.1-D1 tests — three-tier topology diff views (build/review/conflict)."""

from __future__ import annotations

import pytest

from l4.sandbox.sandbox_diff import build_diff, check_conflict, conflict_diff, review_diff

OLD = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
NEW = "def foo():\n    return 10\n\ndef bar():\n    return 2\n"


# ── Tier 1: build ──


def test_build_diff_precise_hunks():
    """Build tier returns precise hunks + unified view + stats."""
    r = build_diff(OLD, NEW, agent_id="agent-a", tool_name="write_file", timestamp=1.0)
    assert r["tier"] == "build"
    assert r["agent_id"] == "agent-a"
    assert r["tool_name"] == "write_file"
    assert r["hunks"], "expected at least one hunk"
    assert "def foo()" in r["unified"]
    assert r["stats"]["added_lines"] >= 1
    assert r["stats"]["removed_lines"] >= 1


def test_build_diff_empty_when_identical():
    """Identical text yields no hunks."""
    r = build_diff("same\n", "same\n")
    assert r["hunks"] == []
    assert r["stats"]["hunks"] == 0


def test_build_diff_attribution_on_hunks():
    """Each hunk carries the generating agent/tool attribution."""
    r = build_diff(OLD, NEW, agent_id="agent-b", tool_name="edit_file")
    for h in r["hunks"]:
        assert h["agent_id"] == "agent-b"
        assert h["tool_name"] == "edit_file"


# ── Tier 2: review ──


def test_review_diff_structured_with_attribution():
    """Review tier adds per-hunk attribution and optional context."""
    r = review_diff(
        OLD, NEW, rel_path="systems/python-reference-runtime/foo.py", agent_id="agent-a", tool_name="write_file"
    )
    assert r["tier"] == "review"
    assert r["rel_path"] == "systems/python-reference-runtime/foo.py"
    assert r["attribution"], "expected per-hunk attribution"
    first = r["attribution"][0]
    assert first["agent_id"] == "agent-a"
    assert first["tool_name"] == "write_file"
    assert "semantic" in first
    assert r["stats"]["hunks"] == len(r["hunks"])


def test_review_diff_custom_context():
    """context_lines widens the surrounding context attached to hunks."""
    r = review_diff(OLD, NEW, context_lines=2)
    assert all(len(h["context_before"]) <= 2 for h in r["hunks"])


# ── Tier 3: conflict ──


def test_conflict_diff_none():
    """No other agent touching the file → conflict level none."""
    r = conflict_diff("systems/python-reference-runtime/a.py", "agent-a", path_index={}, entries={})
    assert r["tier"] == "conflict"
    assert r["level"] == "none"
    assert r["actionable"] is False


def test_conflict_diff_block_other_agent():
    """Another agent with fresh pending changes → block (actionable)."""
    import time

    entries = {
        "cell-1::systems/python-reference-runtime/a.py::agent-b": type(
            "E", (), {"agent_id": "agent-b", "status": "pending", "modified_at": time.time()}
        )()
    }
    r = conflict_diff(
        "systems/python-reference-runtime/a.py",
        "agent-a",
        path_index={
            "systems/python-reference-runtime/a.py": ["cell-1::systems/python-reference-runtime/a.py::agent-b"]
        },
        entries=entries,
    )
    assert r["level"] == "block"
    assert r["actionable"] is True


def test_check_conflict_consistent_with_tier3():
    """conflict_diff wraps check_conflict (same level)."""
    level = check_conflict("systems/python-reference-runtime/a.py", "agent-a", path_index={}, entries={})
    assert level == "none"


# ── API surface ──


@pytest.fixture()
def _heavy_api_enabled():
    """Enable the diff heavy API for the API-surface tests.

    _is_enabled() reads the L3 SettingsCenter (get_center), so the toggle
    must be set there, not on the L1 settings object.
    """
    from l3.config.settings_center import get_center

    get_center().set("diff.heavy_api_enabled", True)
    yield
    get_center().set("diff.heavy_api_enabled", False)


def test_diff_tier_api_build(_heavy_api_enabled):
    """POST /api/v2/diff/tier with tier=build returns the build view."""
    from l4.api.api_handlers_diff import diff_tier

    r = diff_tier({"tier": "build", "old_text": OLD, "new_text": NEW, "agent_id": "agent-a"})
    assert r["success"] is True
    assert r["tier"] == "build"
    assert r["diff"]["hunks"]


def test_diff_tier_api_invalid_tier(_heavy_api_enabled):
    """Unknown tier returns a structured error."""
    from l4.api.api_handlers_diff import diff_tier

    r = diff_tier({"tier": "bogus"})
    assert r["success"] is False
    assert "invalid tier" in r["error"]
