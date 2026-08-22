"""Durability tests for session_json — atomic writes and cursor hardening.

Covers the second-round optimizations:
  - conversation/thought/tool files use atomic write + dir fsync;
  - cursor atomic_update with mirror>base and fail-closed.
"""

from __future__ import annotations

import json
import threading

import pytest

from l3.durable_store import DurableJsonStore


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    """Isolate sessions_dir and cursor to tmp_path."""
    from l3.cell.peers.l3a import session_json as sj

    monkeypatch.setattr(sj, "sessions_dir", lambda: tmp_path / "l3a" / "sessions")
    # Ensure _session_dir also points there (fallback path).
    monkeypatch.setattr(sj, "_session_dir", lambda: tmp_path / "l3a" / "sessions")
    sj.reset_sequences()
    yield sj, tmp_path
    sj.reset_sequences()


def test_append_turn_is_atomic_and_sorted(iso):
    """append_turn replaces same seq and keeps entries sorted."""
    sj, tmp_path = iso
    sj.append_turn("s-1", 2, "user2", "asst2")
    sj.append_turn("s-1", 1, "user1", "asst1")
    sj.append_turn("s-1", 2, "user2b", "asst2b")  # overwrite seq 2
    data = sj.load_conversation("s-1")
    seqs = [e["seq"] for e in data["entries"]]
    assert seqs == [1, 2]
    # Last write wins for seq 2.
    assert data["entries"][1]["user"]["content"] == "user2b"
    # File is valid JSON (not half-written).
    raw = (tmp_path / "l3a" / "sessions" / "s-1_conversation.json").read_text(encoding="utf-8")
    assert json.loads(raw) == data


def test_append_thought_sorted_and_atomic(iso):
    """append_thought keeps (turn,seq) sorted and is atomic."""
    sj, tmp_path = iso
    sj.append_thought("s-2", 2, 2, "reason2")
    sj.append_thought("s-2", 1, 1, "reason1")
    sj.append_thought("s-2", 1, 1, "reason1b")  # overwrite same (turn,seq)
    data = sj.load_thoughts("s-2")
    assert [(t["turn"], t["seq"]) for t in data["thoughts"]] == [(1, 1), (2, 2)]
    assert data["thoughts"][0]["content"] == "reason1b"
    raw = (tmp_path / "l3a" / "sessions" / "s-2_thoughts.json").read_text(encoding="utf-8")
    assert json.loads(raw) == data


def test_record_failed_tool_atomic(iso):
    """record_failed_tool appends atomically and valid JSON."""
    sj, tmp_path = iso
    sj.record_failed_tool("s-3", 1, "cardwrite", "err1")
    sj.record_failed_tool("s-3", 2, "l3a_spawn", "err2")
    data = sj.load_tool_failures("s-3")
    assert len(data["failures"]) == 2
    assert data["failures"][0]["tool"] == "cardwrite"
    raw = (tmp_path / "l3a" / "sessions" / "s-3_tools.json").read_text(encoding="utf-8")
    assert json.loads(raw) == data


def test_history_atomic(iso):
    """History open/close is atomic and queryable."""
    sj, tmp_path = iso
    sj.record_session_open("h-1", title="t1")
    sj.record_session_close("h-1", task_summary="done")
    q = sj.query_session_history(session_id="h-1")
    assert q["count"] == 1
    assert q["sessions"][0]["task_summary"] == "done"
    raw = (tmp_path / "l3a" / "sessions" / "history.json").read_text(encoding="utf-8")
    assert json.loads(raw)["sessions"][0]["session_id"] == "h-1"


def test_cursor_concurrent_via_threads(iso):
    """Concurrent next_input_seq from threads allocates unique monotonic seqs."""
    sj, tmp_path = iso
    n_threads = 10
    n_per = 20
    results: list[int] = []
    lock = threading.Lock()

    def _worker():
        local: list[int] = []
        for _ in range(n_per):
            local.append(sj.next_input_seq("concurrent"))
        with lock:
            results.extend(local)

    threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == n_threads * n_per
    assert len(set(results)) == len(results)
    assert min(results) == 1
    assert max(results) == n_threads * n_per
    # In-process mirror is consistent with file.
    assert sj._seq["concurrent"] == n_threads * n_per
    # Durable file also holds max.
    from pathlib import Path

    cursor_file = tmp_path / "l3a" / "sessions" / ".input_seq_cursor.json"
    env = json.loads(cursor_file.read_text(encoding="utf-8"))
    assert env["payload"]["cursor"]["concurrent"] == n_threads * n_per


def test_cursor_mirror_ahead_of_file(iso):
    """In-process mirror ahead of file is honored (fast path)."""
    sj, tmp_path = iso
    # Write file with cursor 5.
    store = DurableJsonStore(tmp_path / "l3a" / "sessions" / ".input_seq_cursor.json", kind="l3a_input_seq")
    store.write({"cursor": {"s-m": 5}})
    # Set mirror ahead to 10 (simulates in-mem increments not yet flushed).
    sj._seq["s-m"] = 10
    nxt = sj.next_input_seq("s-m")
    assert nxt == 11
    assert store.read()["cursor"]["s-m"] == 11


def test_append_turn_handles_corrupt_file(iso):
    """Corrupt conversation file is treated as empty and overwritten."""
    sj, tmp_path = iso
    p = tmp_path / "l3a" / "sessions" / "s-corrupt_conversation.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    r = sj.append_turn("s-corrupt", 1, "u", "a")
    assert r["success"] is True
    assert sj.load_conversation("s-corrupt")["entries"][0]["seq"] == 1


def test_next_input_seq_empty_session_id_raises(iso):
    """Empty session_id raises ValueError."""
    sj, _ = iso
    with pytest.raises(ValueError):
        sj.next_input_seq("")


def test_cursor_persists_across_sessions(iso):
    """Cursor is per-session isolated."""
    sj, _ = iso
    assert sj.next_input_seq("a") == 1
    assert sj.next_input_seq("b") == 1
    assert sj.next_input_seq("a") == 2
    assert sj.next_input_seq("b") == 2
