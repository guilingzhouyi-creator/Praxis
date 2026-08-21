"""Validate shared config-discovery vectors against the Python3 reference."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel import discovery

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_discovery_vectors.json"


def test_shared_discovery_vectors_match_python_reference() -> None:
    """Keep defaults, parsed overrides, source snapshots, and fallbacks aligned."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for vector in vectors:
        discovery.reset()
        for name, defaults in vector["defaults"].items():
            discovery.register(name, defaults)
        for name, override in vector["overrides"].items():
            if override is None:
                continue
            current = discovery.get_config(name)
            if isinstance(current, dict) and isinstance(override, dict):
                for key, value in override.items():
                    discovery.set_config(name, key, value)
            elif name in vector["defaults"]:
                discovery._registry[name] = override
        for name, expected in vector["expected_config"].items():
            assert discovery.get_config(name) == expected, (vector["case"], name)
        for name, expected in vector["expected_source"].items():
            assert discovery.get_source(name) == expected, (vector["case"], name)
        for query in vector["tool_queries"]:
            assert discovery.get_tool_config(query["key"], query["default"]) == query["expected"]
        for query in vector["service_queries"]:
            assert discovery.get_service_limit(query["key"], query["default"]) == query["expected"]
    discovery.reset()
