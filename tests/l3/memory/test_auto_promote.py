"""Tests for the ring-promotion ladder (P1-①)."""

from __future__ import annotations


def _fresh_memory(tmp_path, monkeypatch):
    """Build an isolated memory manager for promotion testing."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path))
    from l3.memory.memory import MemoryManager, reset_memory

    reset_memory()
    return MemoryManager(), reset_memory


def test_auto_promote_moves_high_importance(tmp_path, monkeypatch):
    """P1-①: entries clearing the importance threshold are promoted."""
    mem, reset = _fresh_memory(tmp_path, monkeypatch)
    try:
        mem.remember(agent_id="agent-a", entry_type="pattern", content="important pattern", importance=0.8, ring=1)
        mem.remember(agent_id="agent-a", entry_type="observation", content="trivial note", importance=0.2, ring=1)
        promoted = mem.auto_promote(min_importance=0.6, from_ring=1, to_ring=2)
        assert promoted == 1
        # The high-importance entry moved to ring 2 (promote re-remembers
        # under a fresh id, so assert on the ring's entry count). The
        # low-importance entry was rejected at remember (quality gate).
        assert len(list(mem.short._entries)) == 1
        assert len(list(mem.working._entries)) == 0
    finally:
        reset()


def test_auto_promote_noop_below_threshold(tmp_path, monkeypatch):
    """P1-①: no promotion when nothing clears the threshold."""
    mem, reset = _fresh_memory(tmp_path, monkeypatch)
    try:
        mem.remember(agent_id="agent-a", entry_type="observation", content="low", importance=0.2, ring=1)
        promoted = mem.auto_promote(min_importance=0.6, from_ring=1, to_ring=2)
        assert promoted == 0
    finally:
        reset()
