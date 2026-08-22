"""Validate deterministic identity UID issuance vectors against Python."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel import identity_uid

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_identity_uid_vectors.json"


def test_shared_identity_uid_vectors_match_rust_candidate() -> None:
    """Keep bounded candidate issuance and validation aligned across languages."""
    vector = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for case in vector["cases"]:
        identity_uid.reset_identity_uid()
        for tracked in case["tracked"]:
            identity_uid._track_existing(tracked)
        assert identity_uid.issue_identity_uid_from_candidates(case["candidates"]) == case["expected"]
    for case in vector["verify"]:
        assert identity_uid.verify_identity_uid(case["uid"]) is case["expected"]
