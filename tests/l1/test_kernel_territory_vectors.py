"""Validate shared territory containment vectors against the Python3 reference."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.territory import is_within

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_territory_vectors.json"


def test_shared_territory_vectors_match_python_reference() -> None:
    """Keep boundary-safe territory semantics aligned across languages."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for vector in vectors:
        assert is_within(vector["target"], vector["bases"]) is vector["expected"], vector["case"]
