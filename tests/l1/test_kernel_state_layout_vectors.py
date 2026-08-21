"""Validate the Rust-owned state layout vectors at the Python3 adapter boundary."""

from __future__ import annotations

import json
from pathlib import Path


def _python_state_decision(probe: dict, current_version: int) -> tuple[str, str]:
    """Mirror the side-effect-free state action decision for vector checking."""
    action, reason = "reject", "missing_clean_shutdown"
    if not probe["root_exists"]:
        action, reason = "initialize", "missing_root"
    elif probe["root_empty"]:
        action, reason = "initialize", "empty_root"
    else:
        version = probe["manifest_version"]
        if version is None:
            reason = "missing_manifest"
        elif version > current_version:
            reason = "future_layout"
        elif version < current_version:
            action, reason = "migrate", "older_layout"
        elif probe["clean_shutdown"] is True:
            action, reason = "resume", "clean_state"
        elif probe["clean_shutdown"] is False:
            action, reason = "recover", "unclean_shutdown"
    return action, reason


def test_state_layout_vectors_are_deterministic_and_adapter_visible() -> None:
    """Keep fresh layout entries, parent coverage, and recovery decisions stable."""
    vectors = json.loads(Path("tests/fixtures/kernel_state_layout_vectors.json").read_text(encoding="utf-8"))
    assert vectors["entries"]
    assert vectors["expected_entries"] == sorted(vectors["entries"], key=lambda entry: (entry["path"], entry["kind"]))
    directories = {entry["path"] for entry in vectors["expected_entries"] if entry["kind"] == "directory"}
    for entry in vectors["expected_entries"]:
        parts = entry["path"].split("/")
        assert all(part not in {"", ".", ".."} for part in parts)
        for index in range(1, len(parts)):
            assert "/".join(parts[:index]) in directories
    for vector in vectors["probes"]:
        expected = _python_state_decision(vector["probe"], 1)
        assert expected == (vector["expected_action"], vector["expected_reason"])
