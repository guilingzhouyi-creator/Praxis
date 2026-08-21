"""Validate shared SystemBus mechanism vectors against the Python3 reference."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.bus import Component, ComponentMeta, SystemBus, _topological_sort

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_bus_vectors.json"


class _FixtureComponent(Component):
    """Provide a no-side-effect component for contract vectors."""

    def __init__(self, meta: ComponentMeta) -> None:
        self.meta = meta


def _build_bus(vector: dict) -> SystemBus:
    """Build a SystemBus from declarative vector metadata."""
    parent = SystemBus(name="parent")
    for name in vector.get("available", []):
        parent.register(_FixtureComponent(ComponentMeta(name=name)))
    bus = SystemBus(parent=parent, name="fixture")
    for raw in vector["registrations"]:
        bus.register(_FixtureComponent(ComponentMeta(**raw)))
    return bus


def test_shared_bus_vectors_match_python_reference() -> None:
    """Keep registration order, dependency filtering, topology, and states aligned."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for vector in vectors:
        bus = _build_bus(vector)
        names = [component.meta.name for component in bus.list_components()]
        assert names == vector["expected_names"], vector["case"]
        graph = bus._dep_graph(names)
        assert graph == vector["expected_graph"], vector["case"]
        if "expected_cycle" in vector:
            try:
                _topological_sort(names, graph)
            except ValueError as error:
                assert all(name in str(error) for name in vector["expected_cycle"]), vector["case"]
            else:
                raise AssertionError(f"cycle accepted: {vector['case']}")
            continue

        assert _topological_sort(names, graph) == vector["expected_order"], vector["case"]
        bus.install()
        bus.start_all()
        bus.stop_all()
        states = {name.rsplit(".", 1)[-1]: state for name, state in bus.state_map().items()}
        assert states == vector["expected_states"], vector["case"]
        for name, expected in vector.get("expected_specs", {}).items():
            actual = bus.get(name)
            assert actual is not None
            assert actual.meta.__dict__ == expected
