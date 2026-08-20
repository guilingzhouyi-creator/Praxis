"""Shared vectors for the pure system-registry candidate."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.registry import Registry, aggregate_summary, snapshot_sections

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_registry_vectors.json"


def test_shared_registry_vectors_match_python_reference() -> None:
    """Keep section snapshots and explicit summary aggregation deterministic."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for case in vectors["cases"]:
        sections = case["sections"]
        actual_sections = snapshot_sections(sections)
        assert actual_sections == case["expected_sections"], case["name"]

        actual_summary = aggregate_summary(
            case["modules"],
            case["process_count"],
            case["device_count"],
            case["syscalls"],
            case["timestamp"],
            healthy_status=case.get("healthy_status", "PASS"),
        )
        assert actual_summary == case["expected_summary"], case["name"]


def test_registry_sections_snapshot_isolated() -> None:
    """Mutating a returned section snapshot must not mutate the source."""
    source = {"todo_table": {"tasks": ["one"]}}
    snapshot = snapshot_sections(source)
    snapshot["todo_table"]["tasks"].append("two")
    assert source == {"todo_table": {"tasks": ["one"]}}


def test_registry_section_store_uses_sorted_snapshot() -> None:
    """Expose register-backed sections through the isolated snapshot helper."""
    registry = Registry()
    registry.set_section("z", {"value": 1})
    registry.set_section("a", {"value": 2})
    assert list(registry.sections()) == ["a", "z"]
