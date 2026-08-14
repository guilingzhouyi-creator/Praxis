"""Phase-3 M4 tests — memory RC record source (memory source + correction corpus export)."""

from __future__ import annotations

import pytest

from l3.memory.memory_record_source import _export, _query, _stats, register_memory_source


@pytest.fixture(autouse=True)
def _clean():
    from l3.memory.tiered_cache import reset_tiered_cache

    reset_tiered_cache()
    yield
    reset_tiered_cache()


def _seed_records():
    from l3.memory.tiered_cache import get_tiered_cache

    tc = get_tiered_cache()
    tc.index_archive(
        "memory:refined_records",
        {
            "records": [
                {
                    "content": "refined insight about the allocator for training correction",
                    "entry_type": "l3a_tool_decision",
                    "cell_id": "cell-1",
                    "agent_id": "a1",
                    "tags": ["review"],
                    "refinery_score": 12.5,
                    "ts": 100.0,
                },
                {
                    "content": "second refined insight for the correction corpus sample",
                    "entry_type": "note",
                    "cell_id": "cell-2",
                    "agent_id": "a2",
                    "tags": ["build"],
                    "refinery_score": 8.0,
                    "ts": 200.0,
                },
            ]
        },
    )


def test_query_returns_records():
    """query() returns refined-memory records (limit respected)."""
    _seed_records()
    assert len(_query()) == 2
    assert len(_query(limit=1)) == 1
    assert len(_query(since=150.0)) == 1


def test_stats_shape():
    """stats() aggregates domains and types."""
    _seed_records()
    s = _stats()
    assert s["memory_records"] == 2
    assert "cell-1" in s["domains"]
    assert "note" in s["types"]


def test_export_correction_corpus():
    """export() produces correction-corpus samples with identity/domain context."""
    _seed_records()
    samples = _export()
    assert len(samples) == 2
    first = samples[0]
    assert first["content"]
    assert first["identity_tags"] == ["review"]
    assert first["cell_id"] == "cell-1"
    assert "refinery_score" in first


def test_export_includes_log_context():
    """export() samples carry a log_context snapshot (event-bus history)."""
    _seed_records()
    samples = _export()
    assert len(samples) == 2
    assert "log_context" in samples[0]
    assert isinstance(samples[0]["log_context"], list)


def test_register_memory_source():
    """register_memory_source adds the memory source to the RecordCenter."""
    r = register_memory_source()
    assert r["success"] is True

    from l3.services.record_center import get_record_center

    stats = get_record_center().stats()
    assert "memory" in stats
