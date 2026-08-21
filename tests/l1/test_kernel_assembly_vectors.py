"""Validate the independent Rust assembly fixture at the Python3 reference boundary."""

from __future__ import annotations

import json
from pathlib import Path


def test_assembly_vectors_preserve_dependency_and_port_order() -> None:
    """Keep the clean-break assembly inputs and deterministic output visible."""
    vectors = json.loads(Path("tests/fixtures/kernel_assembly_vectors.json").read_text(encoding="utf-8"))
    steps = {step["name"]: step for step in vectors["boot_steps"]}
    visited: set[str] = set()
    order: list[str] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        for dependency in steps[name]["depends_on"]:
            visit(dependency)
        visited.add(name)
        order.append(name)

    for step in vectors["boot_steps"]:
        visit(step["name"])
    assert order == vectors["expected_boot_order"]
    assert [port["name"] for port in vectors["ports"]] == vectors["expected_port_order"]
