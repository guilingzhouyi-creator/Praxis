"""2.1 directed-fix execution tests — review small fixes land on disk."""

from __future__ import annotations

import pytest

from l3.services.review_pipeline import get_review_pipeline, reset_review_pipeline


@pytest.fixture(autouse=True)
def _clean():
    reset_review_pipeline()
    yield
    reset_review_pipeline()


def _review_diff_with_hunks():
    """A small review diff with a single hunk (old→new replacement)."""
    return {
        "stats": {"changed_lines": 2},
        "hunks": [
            {
                "type": "replace",
                "removed_lines": ["    return 1\n"],
                "added_lines": ["    return 10\n"],
                "modified_start": 2,
                "modified_end": 3,
            }
        ],
    }


def test_small_fix_applies_to_file(tmp_path):
    """A small reviewed hunk is applied to the target file on disk."""
    target = tmp_path / "foo.py"
    target.write_text("def foo():\n    return 1\n", encoding="utf-8")

    pipe = get_review_pipeline()
    r = pipe.dispose(_review_diff_with_hunks(), rel_path=str(target), agent_id="agent-a")

    assert r["disposition"] == "small"
    assert r["fixed"] is True
    assert r["applied"] == 1
    assert "return 10" in target.read_text(encoding="utf-8")


def test_large_change_never_applies(tmp_path):
    """Large changes route to rework — nothing is written to disk."""
    target = tmp_path / "big.py"
    target.write_text("x = 1\n", encoding="utf-8")

    pipe = get_review_pipeline()
    big_diff = {
        "stats": {"changed_lines": 500},
        "hunks": [{"type": "replace", "removed_lines": ["x = 1\n"], "added_lines": ["x = 2\n"]}],
    }
    r = pipe.dispose(big_diff, rel_path=str(target))
    assert r["disposition"] == "large"
    assert r["applied"] == 0
    assert "x = 1" in target.read_text(encoding="utf-8")


def test_no_hunks_no_apply(tmp_path):
    """A small disposition with no hunks applies nothing (0)."""
    pipe = get_review_pipeline()
    r = pipe.dispose({"stats": {"changed_lines": 2}, "hunks": []}, rel_path=str(tmp_path / "x.py"))
    assert r["applied"] == 0


def test_empty_path_no_apply():
    """Missing rel_path skips the directed fix entirely."""
    pipe = get_review_pipeline()
    r = pipe.dispose(_review_diff_with_hunks(), rel_path="")
    assert r["applied"] == 0
