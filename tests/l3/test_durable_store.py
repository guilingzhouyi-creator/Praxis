"""DurableJsonStore contract tests (3.3 P0.4) + input-seq durable cursor (P0.5)."""

from __future__ import annotations

import json
import os

import pytest

from l3.durable_store import DurableJsonStore, DurableStoreError


def _store(tmp_path):
    return DurableJsonStore(tmp_path / "state.json", kind="test_kind")


def test_roundtrip_and_read_absent(tmp_path):
    s = _store(tmp_path)
    assert s.read() == {}
    r = s.write({"k": 1, "nested": {"a": [1, 2]}})
    assert r["success"] is True
    assert s.read() == {"k": 1, "nested": {"a": [1, 2]}}


def test_write_is_idempotent(tmp_path):
    s = _store(tmp_path)
    payload = {"n": 7}
    assert s.write(payload)["success"] is True
    r2 = s.write(payload)
    assert r2["success"] is True
    assert r2.get("idempotent") is True


def test_corrupt_main_recovers_from_journal(tmp_path):
    s = _store(tmp_path)
    s.write({"gen": 1})
    s.write({"gen": 2})
    # Simulate a crash mid-replace: main file truncated/damaged.
    (tmp_path / "state.json").write_text('{"v": 1, "payl', encoding="utf-8")
    assert s.read() == {"gen": 2}
    # Self-heal: the main file is repaired from journal truth.
    env = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert env["payload"] == {"gen": 2}


def test_missing_main_recovers_from_journal(tmp_path):
    """Catastrophic main loss: the journal mirror alone restores state."""
    s = _store(tmp_path)
    s.write({"gen": 1})
    s.write({"gen": 2})
    (tmp_path / "state.json").unlink()
    assert s.read() == {"gen": 2}


def test_damage_beyond_journal_fails_closed(tmp_path):
    s = _store(tmp_path)
    s.write({"keep": True})
    # Trash BOTH main and journal beyond repair.
    (tmp_path / "state.json").write_text("garbage{{{", encoding="utf-8")
    jp = tmp_path / "state.json.journal"
    jp.write_text("not-json\nalso-bad", encoding="utf-8")
    with pytest.raises(DurableStoreError):
        s.read()


def test_locked_store_fails_closed(tmp_path):
    s = _store(tmp_path)
    s.write({"first": True})
    lock_path = tmp_path / "state.json.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = s.write({"second": True})
        assert r["success"] is False
        assert "locked" in r["error"]
        assert s.read() == {"first": True}  # read still allowed; nothing lost
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def test_reset_clears_store(tmp_path):
    s = _store(tmp_path)
    s.write({"x": 1})
    s.reset()
    assert s.read() == {}


# ── P0.5: durable input-seq cursor ──


@pytest.fixture()
def seq_env(monkeypatch, tmp_path):
    """Isolate session_json's cursor store inside tmp_path."""
    from l3.cell.peers.l3a import session_json as sj

    cursor_path = tmp_path / "l3a" / "sessions" / ".input_seq_cursor.json"
    monkeypatch.setattr(
        sj,
        "_cursor",
        lambda: DurableJsonStore(cursor_path, kind="l3a_input_seq"),
    )
    sj.reset_sequences()
    yield sj, tmp_path
    sj.reset_sequences()


def test_cursor_monotonic_within_process(seq_env):
    sj, _ = seq_env
    assert sj.next_input_seq("s-a") == 1
    assert sj.next_input_seq("s-a") == 2
    assert sj.next_input_seq("s-a") == 3
    assert sj.next_input_seq("s-b") == 1  # per-session space


def test_cursor_survives_restart_without_reuse(seq_env):
    """P0.5 core: after 'restart' (fresh process mirror), seqs continue."""
    sj, _ = seq_env
    used = [sj.next_input_seq("s-x") for _ in range(3)]
    assert used == [1, 2, 3]
    # simulate process restart: wipe ONLY the in-process mirror
    sj._seq.clear()
    assert sj.next_input_seq("s-x") == 4  # NOT 1 again
    assert sj.next_input_seq("s-x") == 5


def test_turn_seq_shared_across_ingests(seq_env):
    """P0.5: conversation + thought records of one turn share ONE seq."""
    sj, _ = seq_env

    class _Probe:
        id = "s-turn"
        _turn_input_seq = None
        _turn_seq = sj.__dict__.get("_turn_seq")  # not used; mixin provides it

    from l3.cell.peers.l3a.session_loop import SessionLoopMixin

    probe = _Probe()
    probe._turn_seq = SessionLoopMixin._turn_seq.__get__(probe)
    a = probe._turn_seq()
    b = probe._turn_seq()
    assert a == b == 1


def test_cursor_fail_closed_on_corruption(seq_env):
    sj, tmp_path = seq_env
    sj.next_input_seq("s-f")
    cursor_file = tmp_path / "l3a" / "sessions" / ".input_seq_cursor.json"
    assert cursor_file.exists()
    cursor_file.write_text("{broken", encoding="utf-8")
    jp = cursor_file.parent / (cursor_file.name + ".journal")
    jp.write_text("", encoding="utf-8")

    # next_input_seq must raise (fail-closed), never silently reset to 1
    with pytest.raises(RuntimeError, match="fail-closed"):
        sj.next_input_seq("s-f")
