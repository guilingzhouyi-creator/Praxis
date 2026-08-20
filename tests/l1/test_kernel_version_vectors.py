"""Validate shared schema-version and migration vectors."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

import l1.kernel.versioning as versioning

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_versioning_vectors.json"


@pytest.fixture(autouse=True)
def _fresh_version_registry():
    """Reset module-level migration registrations around fixture tests."""
    importlib.reload(versioning)
    yield
    importlib.reload(versioning)


def test_shared_versioning_vectors_match_python_reference() -> None:
    """Keep stamping, identity migration, and fail-closed errors aligned."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for case in vectors["cases"]:
        data = dict(case["input"])
        if case["case"] == "stamp_snapshot":
            assert versioning.stamp(data, case["kind"]) == case["expect"]
            continue
        if "error" in case:
            with pytest.raises(ValueError) as caught:
                versioning.check_and_migrate(data, case["kind"])
            if case["error"] == "FUTURE_VERSION":
                assert "file version" in str(caught.value)
            else:
                assert "no migration" in str(caught.value)
            continue
        result = versioning.check_and_migrate(data, case["kind"])
        assert result == case["expect"]
