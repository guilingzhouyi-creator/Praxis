"""Validate shared structured-error vectors against the Python3 reference."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.errors import PraxisError

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_error_vectors.json"


def test_shared_error_vectors_match_python_response_shape() -> None:
    """Keep Python3 error responses aligned with the Rust value candidate."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for vector in vectors:
        error = PraxisError(
            vector["code"],
            vector.get("message", ""),
            cause=Exception(vector["cause"]) if vector.get("cause") else None,
            **vector.get("context", {}),
        )
        assert error.to_dict(locale="en") == vector["expected_response"], vector["case"]
