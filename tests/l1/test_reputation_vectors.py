"""Run the shared reputation semantic vectors against the Python3 reference."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from l1.kernel.reputation import ReputationSystem


@pytest.fixture(scope="module")
def vectors() -> dict:
    """Load the language-neutral reputation fixture."""
    path = Path(__file__).parents[1] / "fixtures" / "kernel_reputation_vectors.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_shared_reputation_vectors_match_python_reference(vectors: dict) -> None:
    """Python3 reference follows the same clamp and outcome semantics."""
    policy = vectors["policy"]
    for case in vectors["cases"]:
        reputation = ReputationSystem()
        for operation in case["operations"]:
            kind = operation["kind"]
            agent_id = operation["agent_id"]
            if kind == "get":
                actual = reputation.get(agent_id)
            elif kind == "set":
                reputation.set(agent_id, operation["score"])
                actual = reputation.get(agent_id)
            elif kind == "record_task":
                actual = reputation.record_task(agent_id, operation["success"])
            elif kind == "record_review":
                actual = reputation.record_review(agent_id, operation["approved"])
            elif kind == "record_dispute":
                actual = reputation.record_dispute(agent_id, operation["upheld"])
            else:
                raise AssertionError(f"unknown reputation operation: {kind}")
            if "expected" in operation:
                assert actual == pytest.approx(operation["expected"]), case["name"]
        assert reputation.all() == pytest.approx(case["snapshot"]), case["name"]
    assert policy["default_score"] == pytest.approx(0.85)
