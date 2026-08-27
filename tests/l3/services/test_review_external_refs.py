"""2.1 gap-fill tests — external knowledge references + new-file marker."""

from __future__ import annotations

import pytest

from l3.services.review_pipeline import get_review_pipeline, reset_review_pipeline
from l4.sandbox.sandbox_diff import build_diff


@pytest.fixture(autouse=True)
def _clean():
    reset_review_pipeline()
    yield
    reset_review_pipeline()


def _hunky_review_diff():
    return {
        "stats": {"changed_lines": 2},
        "hunks": [
            {
                "type": "replace",
                "removed_lines": ["    return 1\n"],
                "added_lines": ["    return sanitize(input)\n"],
                "modified_start": 2,
                "modified_end": 3,
            }
        ],
    }


def test_external_references_attached(monkeypatch):
    """dispose attaches external knowledge-base references from web_search."""
    from l3.services import review_pipeline as rp

    def _fake_web_search(args, agent_id=""):
        assert args["query"]  # query built from the hunk's added lines
        return {"items": [{"title": "Sanitize best practice", "url": "https://example.org/sanitize"}]}

    monkeypatch.setattr("l3.tools._web.web_search", _fake_web_search)
    pipe = rp.get_review_pipeline()
    r = pipe.dispose(_hunky_review_diff(), rel_path="systems/python-reference-runtime/x.py")
    assert r["references"] == [{"title": "Sanitize best practice", "url": "https://example.org/sanitize"}]


def test_external_references_degrade_when_tool_fails(monkeypatch):
    """web_search failure degrades to [] without raising."""
    from l3.services import review_pipeline as rp

    def _boom(args, agent_id=""):
        raise RuntimeError("network down")

    monkeypatch.setattr("l3.tools._web.web_search", _boom)
    pipe = rp.get_review_pipeline()
    r = pipe.dispose(_hunky_review_diff(), rel_path="systems/python-reference-runtime/x.py")
    assert r["references"] == []
    assert r["disposition"] == "small"  # review still proceeds


def test_external_references_absent_without_hunks():
    """No hunks → no external reference fetch."""
    pipe = get_review_pipeline()
    r = pipe.dispose({"stats": {"changed_lines": 0}, "hunks": []})
    assert r["references"] == []


def test_build_diff_new_file_marker():
    """Empty old text + non-empty new text marks a new file."""
    r = build_diff("", "def brand_new():\n    pass\n", agent_id="agent-a")
    assert r["is_new_file"] is True
    assert r["tier"] == "build"


def test_build_diff_edit_not_new_file():
    """A normal edit (non-empty old text) is not marked as new."""
    r = build_diff("def foo():\n    return 1\n", "def foo():\n    return 2\n")
    assert r["is_new_file"] is False
