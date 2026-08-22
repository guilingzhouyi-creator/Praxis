"""Validate shared Constitution rule metadata against the Python reference."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.rule_descriptor import RuleDescriptor, str_to_severity

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_constitution_vectors.json"


def test_shared_constitution_rule_metadata_is_deterministic() -> None:
    """Keep custom rule identity, severity, source, and sorted tags stable."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    descriptors = [
        RuleDescriptor(
            id=rule["id"],
            section=rule["section"],
            severity=str_to_severity(rule["severity"]),
            description=rule["description"],
            source=rule["source"],
            tags=frozenset(rule["tags"]),
        )
        for rule in vectors["valid_rules"]
    ]
    assert [descriptor.id for descriptor in descriptors] == vectors["expected_ids"]
    for descriptor in descriptors:
        serialized = descriptor.to_dict()
        assert serialized["source"] == "custom"
        assert serialized["tags"] == vectors["expected_tags"][descriptor.id]
