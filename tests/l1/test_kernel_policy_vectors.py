"""Validate shared Python3/Rust GateChain and Constitution policy vectors."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.constitution import get_constitution, reset_constitution
from l1.kernel.gatechain import GateResult, LedgerEntry, get_gatechain, reset_gatechain

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_policy_vectors.json"


def test_shared_policy_vectors_match_python_reference() -> None:
    """Keep the Rust candidate inputs aligned with Python3 decisions."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for vector in vectors:
        expected = vector["expect"]
        input_data = vector["input"]
        if vector["kind"] == "gatechain":
            reset_gatechain()
            gate = get_gatechain()
            gate.replace_tools(vector.get("tools", []))
            for _ in range(vector.get("history_count", 0)):
                gate.ledger.record(
                    LedgerEntry(
                        agent_id=input_data["agent_id"],
                        tool=input_data["tool"],
                        target="",
                        result=GateResult.PASS,
                    )
                )
            result = gate.check(
                input_data["tool"],
                input_data["agent_id"],
                target=input_data.get("target", ""),
                territory=input_data.get("territory") or [],
                danger=input_data.get("danger_override"),
                pre_approved=input_data.get("pre_approved", False),
                interactive=input_data.get("interactive", False),
                reputation=input_data.get("reputation", -1.0),
            )
            assert result["allowed"] is expected["allowed"]
            assert result["decision"] == expected["decision"]
            if "blocked_gate" in expected:
                assert (
                    next(step["gate"] for step in result["steps"] if step["result"] == "BLOCK")
                    == expected["blocked_gate"]
                )
        elif vector["kind"] == "constitution":
            reset_constitution()
            result = get_constitution().is_allowed(
                input_data["action"],
                input_data["agent_id"],
                target=input_data.get("target", ""),
                territory=input_data.get("territory") or [],
            )
            assert result["allowed"] is expected["allowed"]
            assert result["decision"] == expected["decision"]
        else:
            raise AssertionError(f"unknown policy vector kind: {vector['kind']}")
