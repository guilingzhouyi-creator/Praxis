"""Validate shared tool-chain fingerprint vectors against Python3."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.tool_chain import (
    CallLink,
    compute_fingerprint,
    normalize_call_data,
    verify_fingerprint_chain,
)

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_tool_chain_vectors.json"


def test_shared_tool_chain_vectors_match_python_reference() -> None:
    """Keep normalization, HMAC truncation, GENESIS, and tamper results aligned."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    secret_key = vectors["secret_key"].encode()
    for case in vectors["cases"]:
        previous = ""
        links = []
        for raw in case["links"]:
            normalized = normalize_call_data(
                raw["tool_name"],
                raw["agent_id"],
                raw["ring"],
                raw["call_id"],
                raw["parent_id"],
                raw["depth"],
            )
            assert normalized == raw["normalized"], case["name"]
            assert compute_fingerprint(secret_key, normalized, previous) == raw.get(
                "canonical_fingerprint", raw["fingerprint"]
            ), case["name"]
            previous = raw["fingerprint"]
            links.append(CallLink(**{key: raw[key] for key in CallLink.__dataclass_fields__ if key in raw}))
        assert verify_fingerprint_chain(secret_key, links) == case["expected"], case["name"]
