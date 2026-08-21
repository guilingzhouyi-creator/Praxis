"""Cross-language control vectors for the Python3 identity-binding adapter."""

from __future__ import annotations

import json
from pathlib import Path


def test_shared_identity_binding_vectors_match_python_adapter(tmp_path, monkeypatch):
    """Keep write authorization and mutation lifecycle aligned with Rust."""
    monkeypatch.setenv("PRAXIS_IDENTITY_STATE", str(tmp_path / "identity.json"))
    from l1.kernel.identity_binding import (
        get_identity_binding_manager,
        reset_identity_binding_manager,
    )

    vectors = json.loads(Path("tests/fixtures/kernel_identity_binding_vectors.json").read_text(encoding="utf-8"))
    reset_identity_binding_manager()
    manager = get_identity_binding_manager()
    try:
        for case in vectors["authorization"]:
            allowed, _ = manager.authorize_write(
                agent_id=case["agent_id"],
                role=case["role"],
                internal=case["internal"],
            )
            assert allowed is case["allowed"]

        for case in vectors["mutations"]:
            if case["kind"] == "upsert":
                result = manager.bind(
                    case["cell_id"],
                    case["role"],
                    "adapter-owned fragment",
                    internal=case["internal"],
                )
                assert result["success"] is case["expected"]
            elif case["kind"] == "unbind":
                result = manager.unbind(
                    case["cell_id"],
                    case["role"],
                    internal=case["internal"],
                )
                assert result["success"] is case["expected"]
            elif case["kind"] == "clear":
                result = manager.clear_cell(
                    case["cell_id"],
                    internal=case["internal"],
                )
                assert result["success"] is True
            else:
                raise AssertionError(f"unknown identity-binding operation: {case['kind']}")

        assert manager.revision() == vectors["expected_revision"]
        assert manager.cell_ids() == vectors["expected_cells"]
    finally:
        reset_identity_binding_manager()
