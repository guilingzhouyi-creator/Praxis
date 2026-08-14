"""2.1-D7 tests — diff RC record source: line-precise relevance scoring."""

from __future__ import annotations

import pytest

from l3.services.diff_record_source import (
    build_line_records,
    line_score_for_hunk,
    register_diff_source,
)


def test_line_score_added_weighted():
    """Added lines score by the added weight."""
    hunk = {"added_lines": ["x"] * 2, "removed_lines": []}
    # 2 * 1.0 * 1.3 (reviewed bonus) = 2.6
    assert line_score_for_hunk(hunk, reviewed=True) == pytest.approx(2.6)


def test_line_score_removed_weighted():
    """Removed lines score by the removed weight."""
    hunk = {"added_lines": [], "removed_lines": ["x"] * 2}
    # 2 * 0.7 * 1.3 = 1.82
    assert line_score_for_hunk(hunk, reviewed=True) == pytest.approx(1.82)


def test_line_score_capped():
    """Scores are capped at the per-hunk maximum."""
    hunk = {"added_lines": ["x"] * 20, "removed_lines": []}
    assert line_score_for_hunk(hunk, reviewed=True) <= 5.0


def test_build_line_records_one_per_hunk():
    """One line-precise record per hunk with line ranges."""
    hunks = [
        {"added_lines": ["a", "b"], "removed_lines": [], "modified_start": 10, "modified_end": 12},
        {"added_lines": [], "removed_lines": ["c"], "original_start": 3, "original_end": 4},
    ]
    records = build_line_records("src/foo.py", hunks, reviewed=True)
    assert len(records) == 2
    assert records[0]["path"] == "src/foo.py"
    assert records[0]["line_start"] == 10
    assert records[0]["added_lines"] == 2
    assert records[1]["reviewed"] is True


def test_register_diff_source():
    """register_diff_source adds the diff source to the RecordCenter."""
    r = register_diff_source()
    assert r["success"] is True

    from l3.services.record_center import get_record_center

    # Extra-source aggregates surface as a top-level "diff" key in stats().
    stats = get_record_center().stats()
    assert "diff" in stats
    assert "diff_records" in stats["diff"]
