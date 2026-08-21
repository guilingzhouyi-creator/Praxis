"""Validate shared string-event schema registry vectors against Python3."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel import schema

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_schema_vectors.json"


def test_shared_schema_vectors_match_python_reference() -> None:
    """Keep owner conflict, idempotent updates, sorting, and membership aligned."""
    vector = json.loads(_VECTORS.read_text(encoding="utf-8"))
    schema.reset_event_schema()
    for registration in vector["registrations"]:
        assert schema.register_event(**registration)
    assert schema.list_events() == vector["expected"]
    for name in vector["has"]:
        assert schema.has_event(name)
    for name in vector["missing"]:
        assert not schema.has_event(name)
    schema.reset_event_schema()
