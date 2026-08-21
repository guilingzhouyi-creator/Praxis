"""Validate shared registry-base vectors against the Python3 reference."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from l1.kernel.registry_base import MapRegistry, RegisterableSpec

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_registry_base_vectors.json"


def _spec(raw: dict) -> RegisterableSpec:
    """Build a Python3 descriptor from a fixture object."""
    return RegisterableSpec(**raw)


def test_shared_registry_base_vectors_match_rust_candidate() -> None:
    """Keep duplicate rejection, ordering, filtering, and public views aligned."""
    vector = json.loads(_VECTORS.read_text(encoding="utf-8"))
    registry: MapRegistry[RegisterableSpec] = MapRegistry(allow_overwrite=vector["allow_overwrite"])
    actual_register = [registry.register(_spec(raw), source="fixture") for raw in vector["registrations"]]
    assert actual_register == vector["expected_register"]
    assert registry.all_names() == vector["expected_names"]
    assert [spec.name for spec in registry.list_items(category=vector["category"])] == vector["expected_category_names"]
    for lookup in vector["get"]:
        actual = registry.get(lookup["name"])
        assert (asdict(actual) if actual is not None else None) == (
            asdict(RegisterableSpec(**lookup["expected"])) if lookup["expected"] is not None else None
        )
    assert registry.stats() == vector["expected_stats"]
    assert [spec.to_dict() for spec in registry.list_items()] == vector["expected_public"]
