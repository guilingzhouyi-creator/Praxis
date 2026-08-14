"""Phase-3 M2 tests — memory refinery pipeline (classify/dedup/clean/score/refine/transform)."""

from __future__ import annotations

import pytest

from l3.memory.memory_refinery import get_refinery, reset_refinery


@pytest.fixture(autouse=True)
def _clean():
    reset_refinery()
    yield
    reset_refinery()


def _entry(
    content: str, entry_type: str = "note", tags: list[str] | None = None, importance: float = 1.0, cell_id: str = ""
):
    return {
        "id": content,
        "content": content,
        "entry_type": entry_type,
        "tags": tags or [],
        "importance": importance,
        "cell_id": cell_id,
    }


def test_classify_buckets_by_type():
    """Entries are bucketed by entry_type."""
    r = get_refinery()
    buckets = r.classify([_entry("a", "note"), _entry("b", "l3a_turn_summary")])
    assert "note" in buckets and "l3a_turn_summary" in buckets


def test_dedup_exact_and_prefix():
    """Duplicates drop by exact name or dedup_key prefix (not substring)."""
    r = get_refinery()
    entries = [
        _entry("handle user login flow"),
        _entry("handle user login flow extra detail"),
        _entry("handle user logout flow"),  # different key
    ]
    kept = r.dedup(entries)
    assert len(kept) == 2  # first two dedup (prefix), logout kept


def test_dedup_never_raw_substring():
    """'rm' prefix never swallows 'rmdir'-like distinct entries."""
    r = get_refinery()
    kept = r.dedup([_entry("rm file"), _entry("rmdir dir")])
    assert len(kept) == 2  # distinct keys, no false positive


def test_score_ranks_by_importance_and_tags():
    """Higher importance + more tags → higher refinery_score."""
    r = get_refinery()
    scored = r.score([_entry("a", importance=1.0, tags=["x"]), _entry("b", importance=5.0, tags=["x", "y"])])
    assert scored[0]["refinery_score"] > scored[1]["refinery_score"]


def test_refine_marks_promote_candidates():
    """High-value entries get a promote target ring."""
    r = get_refinery()
    refined = r.refine([{"refinery_score": 50.0, "id": "h"}, {"refinery_score": 5.0, "id": "l"}], target_ring=3)
    by_id = {e["id"]: e for e in refined}
    assert by_id["h"]["promote_to_ring"] == 3
    assert by_id["l"]["promote_to_ring"] == 0


def test_transform_structured_records():
    """Transformed records carry the R5 modeling fields."""
    r = get_refinery()
    records = r.transform(
        [
            {
                "id": "e1",
                "entry_type": "note",
                "cell_id": "c1",
                "agent_id": "a1",
                "tags": ["t"],
                "refinery_score": 4.2,
                "promote_to_ring": 3,
                "content": "x" * 50,
            }
        ]
    )
    assert records[0]["entry_id"] == "e1"
    assert records[0]["refinery_score"] == 4.2


def test_run_pipeline_stats():
    """Full pipeline reports input/deduped/kept/promoted stats."""
    r = get_refinery()
    entries = [
        _entry("login flow implemented", "l3a_turn_summary", importance=4.0),
        _entry("login flow implemented more", "l3a_turn_summary", importance=4.0),  # dedup
        _entry("x", "garbage", importance=0.1),  # cleaned
        # Content long enough to pass the quality gate (> 30 chars) and
        # important enough to promote (score >= HIGH_IMPORTANCE).
        _entry(
            "high value decision approved by the committee after full evidence review of the chain",
            "l3a_tool_decision",
            tags=["review"],
            importance=20.0,
        ),
    ]
    out = r.run_pipeline(entries)
    assert out["success"] is True
    assert out["stats"]["input"] == 4
    assert out["stats"]["deduped"] >= 1
    assert out["stats"]["promoted"] >= 1
    assert len(out["records"]) >= 1


# ── Phase 3 M2 production wiring: operator switch + refine_and_persist ──


def test_refinery_switch_default_off():
    """Refinery master switch defaults off (backward compatible)."""
    assert get_refinery().status()["enabled"] is False


def test_refinery_switch_toggle():
    """set_enabled flips the operator switch."""
    r = get_refinery()
    r.set_enabled(True)
    assert r.status()["enabled"] is True
    r.set_enabled(False)
    assert r.status()["enabled"] is False


def test_refine_and_persist_disabled_noop():
    """refine_and_persist is a no-op while the switch is off."""
    from l3.memory.memory_refinery import refine_and_persist
    from l3.memory.tiered_cache import get_tiered_cache, reset_tiered_cache

    reset_tiered_cache()
    try:
        out = refine_and_persist([_entry("content")])
        assert out["success"] is False
        assert out["persisted"] == 0
        meta = get_tiered_cache().get_archive_index("memory:refined_records") or {}
        assert not meta.get("records")
    finally:
        reset_tiered_cache()


def test_refine_and_persist_writes_archive_index():
    """Enabled: refined records land in the TieredCache archive index (M4 source)."""
    from l3.memory.memory_refinery import refine_and_persist
    from l3.memory.tiered_cache import get_tiered_cache, reset_tiered_cache

    reset_tiered_cache()
    try:
        r = get_refinery()
        r.set_enabled(True)
        entries = [
            _entry(
                "login flow implemented with full session handling and validation",
                "l3a_turn_summary",
                importance=4.0,
            ),
            _entry("login flow implemented with more", "l3a_turn_summary", importance=4.0),  # dedup
        ]
        out = refine_and_persist(entries)
        assert out["success"] is True
        assert out["persisted"] >= 1
        meta = get_tiered_cache().get_archive_index("memory:refined_records") or {}
        records = meta.get("records") or []
        assert len(records) >= 1
        assert records[0]["entry_id"]
    finally:
        reset_tiered_cache()


# ── Phase 3 M2: re-refine ("烧回"/burn-back) stage ──


def test_re_refine_burns_edge_entries_back():
    """re_refine re-scores clean()-dropped entries and may lift them back."""
    r = get_refinery()
    cleaned = [_entry("kept note with enough content", "note", importance=5.0)]
    dropped = [_entry("edge note with enough content to matter", "note", importance=20.0)]
    kept, reburned = r.re_refine(cleaned, dropped)
    assert reburned == 1
    assert len(kept) == 2
    # The reburned entry carried a boost but stays under the promotion bar
    # unless importance already justified it.
    reb = [e for e in kept if e.get("id") == "edge note with enough content to matter"][0]
    assert "refinery_score" in reb


def test_re_refine_low_value_stays_dropped():
    """Trivial dropped entries never burn back (no false promotion)."""
    r = get_refinery()
    cleaned: list[dict] = []
    dropped = [_entry("x", "note", importance=0.1)]
    kept, reburned = r.re_refine(cleaned, dropped)
    assert reburned == 0
    assert kept == []


def test_run_pipeline_reports_reburned():
    """run_pipeline wires re_refine and reports the reburned count."""
    r = get_refinery()
    entries = [
        _entry("solid insight with enough content to pass the gate", "note", importance=5.0),
        # Edge-quality entry: importance high enough that the burn-back lift
        # carries it over the keep bar.
        _entry("edge evidence with enough content to be reconsidered", "note", importance=20.0),
    ]
    out = r.run_pipeline(entries)
    assert out["success"] is True
    assert "reburned" in out["stats"]
    assert out["stats"]["input"] == 2
    assert out["stats"]["kept"] >= 1
