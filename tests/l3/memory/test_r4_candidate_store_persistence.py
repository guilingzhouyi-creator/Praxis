"""Regression tests for indexed and journal-backed candidate persistence."""

from __future__ import annotations

import json
import threading

from l3.memory.r4_candidate_store import CandidateStore


def _record(entry_id: str, content: str = "insight") -> dict[str, str]:
    return {
        "entry_id": entry_id,
        "entry_type": "note",
        "cell_id": "cell-build",
        "agent_id": "agent-builder",
        "role": "builder",
        "content": content,
    }


def test_candidate_enabled_survives_restart(tmp_path):
    """The collection switch is restored independently of the settings center."""
    path = tmp_path / "candidates.json"
    store = CandidateStore(str(path))

    store.set_enabled(False)
    store.flush()

    restored = CandidateStore(str(path))
    assert restored.status()["enabled"] is False
    assert restored.submit_records([_record("memory-1")])["submitted"] == 0


def test_legacy_snapshot_without_enabled_uses_default(tmp_path):
    """Snapshots written before switch persistence remain readable."""
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps({"schema_version": 1, "candidates": []}), encoding="utf-8")

    assert CandidateStore(str(path)).status()["enabled"] is True


def test_journal_replay_restores_mutations_before_compaction(tmp_path):
    """A restart replays recent mutations that have not reached compaction."""
    path = tmp_path / "candidates.json"
    store = CandidateStore(str(path))
    candidate = store.submit_records([_record("memory-1")])["candidates"][0]
    store.submit_records([_record("memory-2")])
    store.flush()

    restored = CandidateStore(str(path)).get(candidate["id"])
    assert restored is not None
    assert len(restored["evidence"]) == 2


def test_submission_uses_fingerprint_index_and_skips_duplicate_persist(tmp_path, monkeypatch):
    """Duplicate evidence resolves through the index without another disk write."""
    store = CandidateStore(str(tmp_path / "candidates.json"))
    first = store.submit_records([_record("memory-1")])["candidates"][0]
    store.flush()
    persist_calls: list[dict] = []
    monkeypatch.setattr(store, "_persist", lambda operation=None: persist_calls.append(operation or {}))

    duplicate = store.submit_records([_record("memory-1")])["candidates"][0]

    assert duplicate["id"] == first["id"]
    assert persist_calls == []
    assert store._fingerprint_index[first["fingerprint"]] == first["id"]


def test_capacity_archives_old_observed_candidates(tmp_path, monkeypatch):
    """The bounded live set archives evicted evidence instead of dropping it."""
    import l3.memory.r4_candidate_store as candidate_module

    monkeypatch.setattr(candidate_module, "R4_CANDIDATE_MAX_RECORDS", 1)
    path = tmp_path / "candidates.json"
    store = CandidateStore(str(path))
    first = store.submit_records([_record("memory-1")])["candidates"][0]
    second = store.submit_records([_record("memory-2", content="other") | {"tags": ["card:other"]}])["candidates"][0]

    assert store.get(first["id"]) is None
    assert store.get(second["id"]) is not None
    archived = path.with_name(f"{path.name}.archive").read_text(encoding="utf-8")
    assert first["id"] in archived


def test_capacity_never_overflows_when_all_candidates_are_lifecycle_protected(tmp_path, monkeypatch):
    """A full ledger rejects new evidence when no lossless eviction is available."""
    import l3.memory.r4_candidate_store as candidate_module

    monkeypatch.setattr(candidate_module, "R4_CANDIDATE_MAX_RECORDS", 1)
    store = CandidateStore(str(tmp_path / "candidates.json"))
    first = store.submit_records([_record("memory-1")])["candidates"][0]
    store.submit_records([_record("memory-2")])
    assert store.validate(first["id"])["success"] is True

    blocked = store.submit_records([_record("memory-3", content="new") | {"tags": ["card:new"]}])

    assert blocked["submitted"] == 0
    assert blocked["capacity_limited"] is True
    assert len(store.list()) == 1
    assert store.get(first["id"])["state"] == "validated"


def test_background_journal_write_releases_candidate_lock(tmp_path, monkeypatch):
    """A slow journal write does not delay an independent ledger read."""
    store = CandidateStore(str(tmp_path / "candidates.json"))
    started = threading.Event()
    release = threading.Event()
    persisted = store._persist

    def blocked_persist(operation=None):
        started.set()
        release.wait()
        persisted(operation)

    monkeypatch.setattr(store, "_persist", blocked_persist)
    try:
        store.submit_records([_record("memory-1")])
        assert started.wait(1)
        reader = threading.Thread(target=store.status)
        reader.start()
        reader.join(1)
        assert not reader.is_alive()
    finally:
        release.set()
        store.flush()


def test_flush_makes_coalesced_journal_entries_durable(tmp_path):
    """An explicit flush creates the durability barrier required by shutdown paths."""
    path = tmp_path / "candidates.json"
    store = CandidateStore(str(path))
    candidate = store.submit_records([_record("memory-1")])["candidates"][0]
    store.submit_records([_record("memory-2")])

    store.flush()

    restored = CandidateStore(str(path)).get(candidate["id"])
    assert restored is not None
    assert len(restored["evidence"]) == 2
