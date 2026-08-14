"""2.1-D5 tests — diff persistence: ring buffer + R4 eviction + API switch."""

from __future__ import annotations

import pytest

from l4.sandbox.diff_persist import get_diff_persist, reset_diff_persist


@pytest.fixture(autouse=True)
def _clean():
    reset_diff_persist()
    yield
    reset_diff_persist()


def test_disabled_by_default():
    """The persist store is off by default (frontend-heavy only)."""
    store = get_diff_persist()
    assert store.enabled() is False


def test_append_rejected_when_disabled():
    """Appending while disabled returns a structured error."""
    store = get_diff_persist()
    r = store.append("d1", "stitched content")
    assert r["success"] is False
    assert "disabled" in r["error"]


def test_enable_and_append():
    """Enabling the store allows stitching diffs into the ring."""
    store = get_diff_persist()
    assert store.set_enabled(True)["success"] is True
    r = store.append("d1", "def foo():\n    return 1\n", meta={"path": "src/a.py"})
    assert r["success"] is True
    assert r["ring"] == 1
    assert store.stats()["ring"] == 1


def test_ring_eviction_compresses_to_r4():
    """Overflow evicts the oldest diff (compressed) and reports to R4."""
    store = get_diff_persist()
    store.set_enabled(True)
    store._capacity = 2
    store.append("d1", "oldest content " * 10)
    store.append("d2", "middle content " * 10)
    store.append("d3", "newest content " * 10)  # evicts d1
    stats = store.stats()
    assert stats["ring"] == 2
    assert stats["evicted_to_r4"] == 1


def test_eviction_reports_event():
    """Eviction records a bus event synchronously (L3A / user notification).

    The bus history is written synchronously before async dispatch, so this
    asserts the record without depending on thread-pool timing.
    """
    from l1.kernel.event import get_bus

    bus = get_bus()
    store = get_diff_persist()
    store.set_enabled(True)
    store._capacity = 1
    store.append("a", "content a")
    store.append("b", "content b")

    matches = [s for s in bus.history(limit=20) if s.get("type") == "diff_evicted_to_r4"]
    assert len(matches) == 1
    assert matches[0]["data"].get("diff_id") == "a"


def test_eviction_archives_to_r4(monkeypatch):
    """Eviction pushes the compressed stream into the R4 archive."""
    from l4.sandbox import diff_persist

    calls = []

    def _fake_archive_store(args, agent_id=""):
        calls.append((args, agent_id))
        return {"success": True}

    monkeypatch.setattr("l3.tools._archive.archive_store", _fake_archive_store)
    store = diff_persist.get_diff_persist()
    store.set_enabled(True)
    store._capacity = 1
    store.append("a", "stitched content " * 20)
    store.append("b", "newer content " * 20)

    assert len(calls) == 1
    args, agent_id = calls[0]
    assert args["fonds"] == "diff"
    assert args["series"] == "stitched"
    assert args["tags"] == "diff_id=a"
    assert agent_id == "diff_persist"


def test_disable_clears_ring():
    """Disabling the store clears the ring buffer."""
    store = get_diff_persist()
    store.set_enabled(True)
    store.append("a", "content")
    store.set_enabled(False)
    assert store.stats()["ring"] == 0


def test_api_switch_handlers():
    """GET/PUT /api/v2/diff/persist expose stats and the enable switch."""
    from l4.api_handlers.api_handlers_security import diff_persist_get, diff_persist_set

    g = diff_persist_get({})
    assert g["success"] is True
    assert g["stats"]["enabled"] is False

    s = diff_persist_set({"enabled": True})
    assert s["success"] is True
    assert s["enabled"] is True
    assert diff_persist_get({})["stats"]["enabled"] is True


def test_frontend_consumes_stitched_diffs():
    """GET /api/v2/diff/stitch serves stitched diffs for the frontend."""
    from l4.api_handlers.api_handlers_security import diff_persist_list

    store = get_diff_persist()
    store.set_enabled(True)
    store.append("d1", "def foo():\n    return 1\n", meta={"path": "src/a.py"})
    store.append("d2", "def bar():\n    return 2\n", meta={"path": "src/b.py"})

    r = diff_persist_list({"limit": 10})
    assert r["success"] is True
    assert len(r["stitched"]) == 2
    assert r["stitched"][0]["diff_id"] == "d1"
    assert r["stitched"][0]["path"] == "src/a.py"
    assert "def foo" in r["stitched"][0]["stitched"]


def test_frontend_consumption_limited():
    """limit caps the stitched records returned to the frontend."""
    from l4.api_handlers.api_handlers_security import diff_persist_list

    store = get_diff_persist()
    store.set_enabled(True)
    for i in range(5):
        store.append(f"d{i}", f"content {i}")

    r = diff_persist_list({"limit": 2})
    assert len(r["stitched"]) == 2
    assert r["stitched"][-1]["diff_id"] == "d4"  # most recent kept


# ── 2.1-D5: durable side-channel store (JSONL flush + crash recovery) ──


def test_flush_writes_jsonl(tmp_path):
    """Periodic flush appends unflushed stitched diffs to the JSONL store."""
    path = tmp_path / "diff_persist.jsonl"
    store = get_diff_persist()
    store.set_enabled(True)
    store.set_persist_path(str(path))
    store.append("d1", "def foo():\n    return 1\n", meta={"path": "src/a.py"})
    store._flush()  # force the periodic write

    assert path.exists()
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    assert '"diff_id": "d1"' in lines[0]
    assert store.stats()["persisted"] == 1


def test_flush_is_incremental(tmp_path):
    """Only unflushed records are written — appends never duplicate."""
    path = tmp_path / "diff_persist.jsonl"
    store = get_diff_persist()
    store.set_enabled(True)
    store.set_persist_path(str(path))
    store.append("d1", "first")
    store._flush()
    store.append("d2", "second")
    store._flush()

    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2
    assert '"d1"' in lines[0] and '"d2"' in lines[1]


def test_recover_replays_jsonl(tmp_path):
    """recover() replays the JSONL store back into the ring (crash recovery)."""
    from l4.sandbox.diff_persist import DiffPersistStore

    path = tmp_path / "diff_persist.jsonl"
    store = DiffPersistStore(persist_path=str(path))
    store.set_enabled(True)
    store.append("d1", "alpha content")
    store.append("d2", "beta content")
    store._flush()

    # A fresh instance (not the singleton) replays the durable store.
    fresh = DiffPersistStore(persist_path=str(path))
    fresh.set_enabled(True)
    n = fresh.recover()
    assert n == 2
    ids = [r["diff_id"] for r in fresh._ring]
    assert ids == ["d1", "d2"]


def test_recover_absent_file_returns_zero(tmp_path):
    """recover() on a missing store returns 0 (no raise)."""
    store = get_diff_persist()
    store.set_persist_path(str(tmp_path / "missing.jsonl"))
    assert store.recover() == 0


def test_recover_respects_capacity(tmp_path):
    """Recovery replays only records persisted in JSONL; ring capacity is honored."""
    from l4.sandbox.diff_persist import DiffPersistStore

    path = tmp_path / "diff_persist.jsonl"
    store = DiffPersistStore(persist_path=str(path))
    store.set_enabled(True)
    store._capacity = 3
    for i in range(5):
        store.append(f"d{i}", f"content {i}")
    store._flush()

    # Only the 3 records left in the ring were flushed; the 2 evicted ones
    # were compressed to R4 (never in the JSONL), so recovery returns 3.
    fresh = DiffPersistStore(persist_path=str(path))
    fresh.set_enabled(True)
    fresh._capacity = 3
    n = fresh.recover()
    assert n == 3
    assert len(fresh._ring) == 3


# ── 2.1 Phase 2: L3 archive tier (Zstd-19) ──


def test_archive_compress_zstd19_prefix():
    """L3 archive re-compression adds the PDZ19 marker (zstd level 19)."""
    store = get_diff_persist()
    binary = b"def foo():\n    return 1\n" * 20
    out = store._archive_compress(binary)
    assert out.startswith(b"PDZ19")
    assert len(out) < len(binary)  # actually compressed


def test_archive_eviction_wraps_zstd19(monkeypatch):
    """Ring eviction archives the L3-wrapped (PDZ19) frame to R4."""
    from l4.sandbox import diff_persist

    calls = []

    def _fake_archive_store(args, agent_id=""):
        calls.append((args, agent_id))
        return {"success": True}

    monkeypatch.setattr("l3.tools._archive.archive_store", _fake_archive_store)
    store = diff_persist.get_diff_persist()
    store.set_enabled(True)
    store._capacity = 1
    store.append("a", "content a")
    store.append("b", "content b")

    assert len(calls) == 1
    stored = calls[0][0]["content"].encode("latin-1")
    assert stored.startswith(b"PDZ19")
