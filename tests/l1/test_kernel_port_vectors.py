"""Validate shared port values against Python's mechanism-port reference."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path


def test_shared_port_values_and_descriptor_order() -> None:
    """Keep value serialization and declarative adapter order language-neutral."""
    from l1.kernel.ports.types import Endpoint, Event, InputActivitySnapshot, Message, Result

    vectors = json.loads(Path("tests/fixtures/kernel_port_vectors.json").read_text(encoding="utf-8"))
    values = vectors["values"]
    assert asdict(Result.ok()) == values["result_ok"]
    assert asdict(Endpoint(**values["endpoint"])) == values["endpoint"]
    message = Message(
        type=values["message"]["type"],
        source=values["message"]["source"],
        target=values["message"]["target"],
        payload=values["message"]["payload"],
        timestamp=values["message"]["timestamp"],
        locale=values["message"]["locale"],
        headers=values["message"]["headers"],
    )
    assert asdict(message) == values["message"]
    activity = InputActivitySnapshot(**values["input_activity"])
    assert asdict(activity) == values["input_activity"]
    assert vectors["expected_order"] == [entry["name"] for entry in vectors["descriptors"]]
    assert Event(type="port.ready", source="kernel", data={}).type == "port.ready"
