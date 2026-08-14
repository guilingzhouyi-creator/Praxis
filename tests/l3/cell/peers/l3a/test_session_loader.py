"""Tests for the decision-layer context loader (3.3, P2-②)."""

from __future__ import annotations

from l3.cell.peers.l3a.session_json import append_turn, reset_sequences
from l3.cell.peers.l3a.session_loader import dynamic_loader, load_for_window


def test_dynamic_loader_pagination_and_label_alternation(tmp_path, monkeypatch):
    """P2-②: paginated window with user/assistant label alternation."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path / "loader"))
    reset_sequences()
    try:
        sid = "sess-load"
        append_turn(sid, 1, "q1", "a1")
        append_turn(sid, 2, "q2", "a2")
        r = load_for_window(sid, page=0, page_size=10)
        assert r["success"] is True
        assert r["total"] == 2
        assert r["dispatched"] == 2
        first = r["entries"][0]
        assert first["user"]["tag"] == "user"
        assert first["assistant"]["tag"] == "assistant"
        assert first["user"]["content"] == "q1"
    finally:
        reset_sequences()


def test_dynamic_loader_cache_hits(tmp_path, monkeypatch):
    """P2-②: already-sent seqs are cache hits (content omitted)."""
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path / "loader2"))
    reset_sequences()
    try:
        sid = "sess-load2"
        append_turn(sid, 1, "q1", "a1")
        append_turn(sid, 2, "q2", "a2")
        r = dynamic_loader(sid, page=0, page_size=10, sent_seqs={1})
        assert r["cache_hits"] == 1
        cached = [e for e in r["entries"] if e.get("cached")]
        assert len(cached) == 1
        assert cached[0]["user"] == ""  # content omitted on hit
    finally:
        reset_sequences()


def test_dynamic_loader_empty_session(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path / "loader3"))
    reset_sequences()
    try:
        r = load_for_window("no-such-session")
        assert r["success"] is True
        assert r["total"] == 0
        assert r["entries"] == []
    finally:
        reset_sequences()
