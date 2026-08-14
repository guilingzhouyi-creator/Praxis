"""Tests for memory write-path → reference-channel linkage (A2)."""

from __future__ import annotations


def test_remember_emits_memory_refined_rc_event(tmp_path, monkeypatch):
    """A write emits exactly one memory_refined event on a fresh RC path."""
    monkeypatch.setenv("PRAXIS_RC_PATH", str(tmp_path / "rc.jsonl"))
    from l3.bus.reference_channel import get_rc, reset_rc

    reset_rc()
    try:
        from l3.memory.memory import MemoryManager

        MemoryManager().remember(
            "a1",
            "note",
            "RC linkage test entry 5522 with enough length to pass quality check",
            tags=[],
            cell_id="cell-9",
        )
        rc = get_rc()
        rc.flush()
        assert rc.count("memory_refined") == 1
        evs = rc.export(limit=5, event_type="memory_refined")
        assert evs
        assert evs[0]["source"] == "memory_ingest"
        data = evs[0]["data"]
        assert data["cell_id"] == "cell-9"
        assert data["ring"] == "R1"
    finally:
        reset_rc()
