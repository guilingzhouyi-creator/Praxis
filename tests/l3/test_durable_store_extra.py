"""Extra edge cases for DurableJsonStore — checksum and empty payload."""

from __future__ import annotations

import json

from l3.durable_store import DurableJsonStore


def _s(tmp_path):
    return DurableJsonStore(tmp_path / "extra.json", kind="extra_kind")


def test_empty_dict_payload_roundtrip(tmp_path):
    """Empty dict payload is valid and roundtrips."""
    s = _s(tmp_path)
    assert s.write({})["success"] is True
    assert s.read() == {}


def test_unicode_payload_canonical(tmp_path):
    """Unicode keys/values are canonicalized with ensure_ascii=False."""
    s = _s(tmp_path)
    payload = {"键": "值", "emoji": "🚀"}
    s.write(payload)
    assert s.read() == payload
    # Canonical form is deterministic.
    raw = (tmp_path / "extra.json").read_text(encoding="utf-8")
    env = json.loads(raw)
    assert "键" in env["payload"]


def test_overwrite_with_same_canonical_is_idempotent(tmp_path):
    """Different insertion order but same canonical is idempotent."""
    s = _s(tmp_path)
    s.write({"x": 1, "y": 2})
    r = s.write({"y": 2, "x": 1})
    assert r.get("idempotent") is True


def test_corrupt_journal_ignored_when_main_ok(tmp_path):
    """Corrupt journal does not affect read when main is healthy."""
    s = _s(tmp_path)
    s.write({"a": 1})
    (tmp_path / "extra.json.journal").write_text("not json\n{{", encoding="utf-8")
    assert s.read() == {"a": 1}


def test_write_after_journal_corruption_recovers(tmp_path):
    """Write succeeds even when journal is corrupt, then heals."""
    s = _s(tmp_path)
    s.write({"a": 1})
    (tmp_path / "extra.json.journal").write_text("bad", encoding="utf-8")
    assert s.write({"a": 2})["success"] is True
    assert s.read() == {"a": 2}


def test_read_absent_returns_empty(tmp_path):
    """Absent file returns {} without raising."""
    s = _s(tmp_path)
    assert s.read() == {}
    assert not (tmp_path / "extra.json").exists()
