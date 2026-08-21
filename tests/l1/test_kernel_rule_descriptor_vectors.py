"""Validate shared rule descriptor value vectors against Python3."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.rule_descriptor import RuleDescriptor, RuleSeverity, str_to_severity

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_rule_descriptor_vectors.json"


def test_shared_rule_descriptor_vectors_match_python_reference() -> None:
    """Keep severity fallback and descriptor serialization aligned."""
    vector = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for severity in vector["severity"]:
        assert str_to_severity(severity["input"]).name == severity["expected"]
    rule = RuleDescriptor(
        id="territory.write",
        section="§2.3",
        severity=RuleSeverity.MUST,
        description="stay inside",
        source="custom",
        tags={"write", "territory"},
        created_at=123.0,
    )
    assert rule.to_dict() == vector["rule"]
    assert rule.evaluate("write_file", "agent", "/tmp/x", []).name == "PASS"
