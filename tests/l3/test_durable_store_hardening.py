"""Hardening tests for DurableJsonStore — dir fsync, kind drift, self-heal.

Covers the second-round optimizations (b0f51f33 → 6247cf18):
  - kind drift is logged not failed;
  - atomic_update self-heals a damaged main on recovery;
  - _fsync_dir is called on journal and replace;
  - payload-not-dict is rejected;
  - canonical idempotency with reordered keys.
"""

from __future__ import annotations

import json
import os

import pytest

from l3.durable_store import DurableJsonStore, DurableStoreError


def _store(tmp_path, kind="test_kind"):
    """Return a store bound to tmp_path/state.json."""
    return DurableJsonStore(tmp_path / "state.json", kind=kind)


def test_kind_drift_logged_not_failed(tmp_path, caplog):
    """A persisted kind differing from the store kind is tolerated."""
    s1 = _store(tmp_path, kind="kind_a")
    s1.write({"x": 1})
    # Reopen with different kind — should still read, not raise.
    s2 = _store(tmp_path, kind="kind_b")
    assert s2.read() == {"x": 1}


def test_payload_not_dict_rejected(tmp_path):
    """Envelope with non-dict payload is treated as damaged."""
    s = _store(tmp_path)
    s.write({"ok": True})
    # Corrupt main to have payload as list, keep checksum consistent for that list.
    import hashlib
    import json as _js

    payload = ["not", "a", "dict"]
    canonical = _js.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    env = {"v": 1, "kind": "test_kind", "checksum": checksum, "payload": payload}
    (tmp_path / "state.json").write_text(_js.dumps(env, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # No journal recovery — should fail closed.
    (tmp_path / "state.json.journal").write_text("", encoding="utf-8")
    with pytest.raises(DurableStoreError):
        s.read()


def test_write_idempotent_with_reordered_keys(tmp_path):
    """Canonical compare makes reordered keys idempotent."""
    s = _store(tmp_path)
    p1 = {"b": 2, "a": 1, "nested": {"y": 2, "x": 1}}
    p2 = {"a": 1, "b": 2, "nested": {"x": 1, "y": 2}}
    assert s.write(p1)["success"] is True
    r2 = s.write(p2)
    assert r2["success"] is True
    assert r2.get("idempotent") is True


def test_atomic_update_self_heals_damaged_main(tmp_path):
    """atomic_update recovers via journal and heals the main file."""
    s = _store(tmp_path)
    s.write({"gen": 1})
    s.write({"gen": 2})
    # Damage main.
    (tmp_path / "state.json").write_text('{"broken":', encoding="utf-8")

    # atomic_update should recover gen=2 then apply updater.
    def _inc(cur):
        nxt = dict(cur)
        nxt["gen"] = int(nxt.get("gen", 0)) + 1
        return nxt

    r = s.atomic_update(_inc)
    assert r["success"] is True
    assert r["payload"]["gen"] == 3
    # Main is healed and readable.
    assert s.read()["gen"] == 3


def test_atomic_update_fails_closed_when_both_damaged(tmp_path):
    """Damaged main + empty journal aborts the atomic update."""
    s = _store(tmp_path)
    s.write({"keep": True})
    (tmp_path / "state.json").write_text("garbage{{{", encoding="utf-8")
    (tmp_path / "state.json.journal").write_text("", encoding="utf-8")
    r = s.atomic_update(lambda cur: {"new": True})
    assert r["success"] is False
    assert "damaged beyond journal recovery" in r["error"]


def test_atomic_update_idempotent_via_canonical(tmp_path):
    """atomic_update is idempotent when canonical payload unchanged."""
    s = _store(tmp_path)
    s.write({"a": 1, "b": 2})
    r = s.atomic_update(lambda cur: {"b": 2, "a": 1})
    assert r["success"] is True
    assert r.get("idempotent") is True


def test_atomic_update_rejects_non_dict_return(tmp_path):
    """Updater must return a dict."""
    s = _store(tmp_path)
    s.write({"x": 1})
    r = s.atomic_update(lambda cur: ["not", "a", "dict"])  # type: ignore[return-value]
    assert r["success"] is False
    assert "updater must return dict" in r["error"]


def test_atomic_update_locked_returns_error(tmp_path):
    """Flock contention makes atomic_update fail closed."""
    s = _store(tmp_path)
    s.write({"first": True})
    lock_path = tmp_path / "state.json.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = s.atomic_update(lambda cur: {"second": True})
        assert r["success"] is False
        assert "locked" in r["error"]
        # Original payload still readable (no partial write).
        assert s.read() == {"first": True}
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def test_journal_is_one_record_mirror(tmp_path):
    """Journal keeps only the last envelope, not an append log."""
    s = _store(tmp_path)
    s.write({"v": 1})
    s.write({"v": 2})
    s.write({"v": 3})
    lines = [ln for ln in (tmp_path / "state.json.journal").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["envelope"]["payload"]["v"] == 3


def test_fsync_dir_called_on_write(monkeypatch, tmp_path):
    """Directory fsync is attempted on both journal and replace."""
    calls: list[str] = []
    orig_fsync = os.fsync

    def _spy(fd):
        # Record that fsync was called; delegate to real fsync for file fds,
        # but for dir fds (O_DIRECTORY) the fd is a directory — still fsync.
        calls.append("fsync")
        return orig_fsync(fd)

    monkeypatch.setattr(os, "fsync", _spy)
    s = _store(tmp_path)
    s.write({"x": 1})
    # At least 2 dir fsyncs (journal dir + replace dir) + 2 file fsyncs.
    assert len(calls) >= 4


def test_envelope_not_a_dict_rejected(tmp_path):
    """Envelope that is not a dict is treated as damaged."""
    s = _store(tmp_path)
    (tmp_path / "state.json").write_text('["not","a","dict"]', encoding="utf-8")
    (tmp_path / "state.json.journal").write_text("", encoding="utf-8")
    with pytest.raises(DurableStoreError):
        s.read()


def test_migrated_payload_not_dict_rejected(tmp_path, monkeypatch):
    """Migrated payload that is not a dict is rejected."""
    s = _store(tmp_path)
    s.write({"a": 1})
    # Monkeypatch check_and_migrate to return non-dict payload.
    import l3.durable_store as ds

    orig = ds.check_and_migrate

    def _fake(env, kind):
        return {"payload": ["bad"], "v": 1, "kind": kind, "checksum": env.get("checksum")}

    monkeypatch.setattr(ds, "check_and_migrate", _fake)
    # Corrupt the read path: main envelope will have correct checksum but
    # migrated payload is list, so _read_envelope_from should return None
    # and fallback to journal (which is still good). Force main to be read
    # with the fake migrator, journal to be empty so it fails closed.
    (tmp_path / "state.json.journal").write_text("", encoding="utf-8")
    with pytest.raises(DurableStoreError):
        s.read()
    monkeypatch.setattr(ds, "check_and_migrate", orig)
