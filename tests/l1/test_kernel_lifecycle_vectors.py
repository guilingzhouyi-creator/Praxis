"""Validate shared lifecycle state and install-decision vectors."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.lifecycle import LifecycleRecord, LifecycleRegistry, LifecycleState

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_lifecycle_vectors.json"


def test_shared_lifecycle_paths_match_python_reference() -> None:
    """Keep valid and invalid lifecycle transitions language-neutral."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for path in vectors["paths"]:
        lifecycle = LifecycleRegistry()
        states = [LifecycleState(value) for value in path["states"]]
        for target in states[1:]:
            assert lifecycle.transition(target)
        assert lifecycle.state() is states[-1]

    for invalid in vectors["invalid_transitions"]:
        lifecycle = LifecycleRegistry()
        source = LifecycleState(invalid["from"])
        target = LifecycleState(invalid["to"])
        routes = {
            LifecycleState.HALTED: [],
            LifecycleState.ACTIVE: [LifecycleState.BOOTING, LifecycleState.ACTIVE],
            LifecycleState.DRAINING: [
                LifecycleState.BOOTING,
                LifecycleState.ACTIVE,
                LifecycleState.DRAINING,
            ],
            LifecycleState.CRASHED: [LifecycleState.BOOTING, LifecycleState.CRASHED],
        }
        for step in routes[source]:
            assert lifecycle.transition(step)
        assert lifecycle.state() is source
        assert not lifecycle.transition(target)


def test_shared_install_decisions_match_python_reference(tmp_path: Path) -> None:
    """Keep first-install, schema, and shutdown recovery rules aligned."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for index, case in enumerate(vectors["install_decisions"]):
        path = tmp_path / f"lifecycle-{index}.json"
        path.write_text(json.dumps(case["record"]), encoding="utf-8")
        lifecycle = LifecycleRegistry(str(path))
        assert lifecycle.should_install() is case["should_install"]

        loaded = lifecycle.load()
        assert LifecycleRecord(**case["record"]) == loaded
