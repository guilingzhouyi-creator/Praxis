"""Tests for R4 archive cell-domain tagging + M1 retrieval gating (A1)."""

from __future__ import annotations

from l3.memory.memory_domain_filter import get_memory_filter, reset_memory_filter
from l3.tools._archive import _cmd_archive_store, archive_search


def test_archive_search_parses_cell_tag():
    _cmd_archive_store("F", "S1", "content-cell-a", "l3a,memory_mer,sc1,cell:cell-A")
    r = archive_search({"query": "content-cell-a"}, "tester")
    assert r["success"] is True
    assert any(x.get("cell_id") == "cell-A" for x in r["results"])


def test_archive_m1_cell_gate_hides_other_cell():
    reset_memory_filter()
    try:
        _cmd_archive_store("F", "S2", "content-cell-b", "l3a,memory_mer,sc2,cell:cell-B")
        f = get_memory_filter()
        f.set_switches(enabled=True, fine_grained=False)
        r = archive_search({"query": "content-cell-b", "cell_id": "cell-A"}, "tester")
        ids = [x.get("cell_id", "") for x in r["results"]]
        assert "cell-B" not in ids
    finally:
        reset_memory_filter()


def test_archive_untagged_visible_when_filter_off():
    reset_memory_filter()
    try:
        _cmd_archive_store("F", "S3", "content-plain", "l3a,memory_mer,sc3")
        r = archive_search({"query": "content-plain"}, "tester")
        assert any(x.get("cell_id") == "" for x in r["results"])
    finally:
        reset_memory_filter()
