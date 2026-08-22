"""Validate shared ResourceLimiter vectors against the Python reference."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.resource import ResourceLimiter

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_resource_vectors.json"


def test_shared_resource_vectors_match_python_reference() -> None:
    """Keep profiles, signed accounting, usage, cleanup, and fallback values aligned."""
    vector = json.loads(_VECTORS.read_text(encoding="utf-8"))
    limiter = ResourceLimiter()
    for profile in vector["profiles"]:
        assert limiter.set_profile(profile["agent_id"], **profile["fields"]) == {"success": True}

    for operation in vector["operations"]:
        op = operation["op"]
        agent_id = operation.get("agent_id", "")
        resource = operation.get("resource", "")
        if op == "get_profile":
            actual = limiter.get_profile(agent_id)
        elif op == "set_profile":
            actual = limiter.set_profile(agent_id, **operation.get("fields", {}))
        elif op == "check":
            kwargs = {"cost": operation["cost"]} if "cost" in operation else {}
            actual = limiter.check(agent_id, resource, **kwargs)
        elif op == "release":
            kwargs = {"cost": operation["cost"]} if "cost" in operation else {}
            actual = limiter.release(agent_id, resource, **kwargs)
        elif op == "usage":
            actual = limiter.usage(agent_id)
        elif op == "all_usage":
            actual = limiter.all_usage()
        elif op == "cleanup_agent":
            actual = limiter.cleanup_agent(agent_id)
        else:
            raise AssertionError(f"unknown resource vector operation: {op}")
        assert actual == operation["expected"], (op, agent_id, resource)
