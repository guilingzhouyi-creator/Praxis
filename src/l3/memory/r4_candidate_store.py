"""Persistent candidate ledger for evidence-backed R4 skill evolution."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from contextlib import suppress
from typing import Any, cast

from l1.kernel.params.agent import (
    R4_CANDIDATE_ARCHIVE_SUFFIX,
    R4_CANDIDATE_ENABLED_DEFAULT,
    R4_CANDIDATE_EVIDENCE_SUMMARY_MAX,
    R4_CANDIDATE_FINGERPRINT_LENGTH,
    R4_CANDIDATE_ID_PREFIX,
    R4_CANDIDATE_JOURNAL_COMPACT_ENTRIES,
    R4_CANDIDATE_JOURNAL_SUFFIX,
    R4_CANDIDATE_MAX_EVIDENCE,
    R4_CANDIDATE_MAX_RECORDS,
    R4_CANDIDATE_MIN_EVIDENCE,
    R4_CANDIDATE_SCHEMA_VERSION,
    R4_CANDIDATE_STATE_FILE,
    R4_CANDIDATE_STATE_TRANSITIONS,
    R4_CANDIDATE_STATES,
)
from l1.kernel.params.system import SKILL_POSTURE_DEFAULT, SKILL_POSTURE_VALID
from l1.kernel.paths import get_paths
from l1.kernel.platform import ensure_dir
from l1.kernel.ports import (
    CandidateBinding,
    CandidateCollectionResult,
    CandidateEvidence,
    CandidateLedgerPort,
    CandidateRecord,
    CandidateResult,
    CandidateSnapshot,
    CandidateState,
    CandidateStatus,
)

logger = logging.getLogger(__name__)


def normalize_binding(
    binding: dict[str, Any] | None = None, record: dict[str, Any] | None = None
) -> dict[str, list[str]]:
    """Normalize the injection scope carried by candidate evidence."""
    source = binding if isinstance(binding, dict) else {}
    record = record if isinstance(record, dict) else {}

    def values(key: str, fallback: str = "") -> list[str]:
        raw = source.get(key)
        if raw is None:
            raw = fallback
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        return sorted({value.strip() for value in raw if isinstance(value, str) and value.strip()})

    tags = record.get("tags") or []
    card_natures = values("card_natures")
    if not card_natures:
        card_natures = sorted(
            {tag[len("card:") :] for tag in tags if isinstance(tag, str) and tag.startswith("card:") and tag[5:]}
        )
    postures = values("postures", str(record.get("posture") or SKILL_POSTURE_DEFAULT))
    postures = [posture for posture in postures if posture in SKILL_POSTURE_VALID]
    return {
        "cell_ids": values("cell_ids", str(record.get("cell_id") or "")),
        "roles": values("roles", str(record.get("role") or "")),
        "agent_ids": values("agent_ids", str(record.get("agent_id") or "")),
        "card_natures": card_natures,
        "postures": postures or [SKILL_POSTURE_DEFAULT],
    }


class CandidateStore:
    """Store evidence clusters until they qualify for skill publication."""

    def __init__(self, state_path: str = "") -> None:
        self._lock = threading.RLock()
        # Serialize every operation that changes both the ledger and the
        # skill registry without extending the ledger lock across R4 calls.
        # RLock permits those operations to finish through transition().
        self._lifecycle_lock = threading.RLock()
        self._state_path = state_path or os.path.join(get_paths().data_dir, R4_CANDIDATE_STATE_FILE)
        self._journal_path = f"{self._state_path}{R4_CANDIDATE_JOURNAL_SUFFIX}"
        self._archive_path = f"{self._state_path}{R4_CANDIDATE_ARCHIVE_SUFFIX}"
        self._enabled = R4_CANDIDATE_ENABLED_DEFAULT
        self._candidates: dict[str, dict[str, Any]] = {}
        self._fingerprint_index: dict[str, str] = {}
        self._journal_entries = 0
        # The state lock protects indexes and candidate mutation. A separate
        # single writer coalesces journal work so evidence capture never holds
        # the state lock across filesystem I/O.
        self._persistence_lock = threading.Lock()
        self._pending_candidate_ids: set[str] = set()
        self._pending_removals: set[str] = set()
        self._pending_enabled: bool | None = None
        self._persist_thread: threading.Thread | None = None
        self._restore()

    def status(self) -> CandidateStatus:
        """Return candidate collection state and lifecycle counts."""
        with self._lock:
            counts = {state: 0 for state in R4_CANDIDATE_STATES}
            for candidate in self._candidates.values():
                state = candidate.get("state")
                if state in counts:
                    counts[state] += 1
            return {"enabled": self._enabled, "counts": counts}

    def set_enabled(self, enabled: bool) -> CandidateStatus:
        """Enable or disable candidate collection without clearing evidence."""
        changed = False
        with self._lock:
            normalized = bool(enabled)
            if self._enabled != normalized:
                self._enabled = normalized
                changed = True
            result = self.status()
        if changed:
            self._queue_persist(enabled=normalized)
        return result

    def _restore(self) -> None:
        if os.path.exists(self._state_path):
            try:
                with open(self._state_path, encoding="utf-8") as state_file:
                    data = json.load(state_file)
                if data.get("schema_version") != R4_CANDIDATE_SCHEMA_VERSION:
                    logger.warning("r4 candidate ledger schema mismatch: %s", self._state_path)
                else:
                    self._enabled = bool(data.get("enabled", self._enabled))
                    for candidate in data.get("candidates") or []:
                        self._upsert(candidate)
            except Exception as exc:
                logger.warning("r4 candidate ledger restore failed: %s", exc)
        self._restore_journal()

    def _upsert(self, candidate: Any) -> None:
        """Install a candidate and update its O(1) fingerprint lookup index."""
        if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str):
            return
        previous = self._candidates.get(candidate["id"])
        if previous:
            old_fingerprint = previous.get("fingerprint")
            if isinstance(old_fingerprint, str) and self._fingerprint_index.get(old_fingerprint) == candidate["id"]:
                self._fingerprint_index.pop(old_fingerprint, None)
        self._candidates[candidate["id"]] = candidate
        fingerprint = candidate.get("fingerprint")
        if isinstance(fingerprint, str) and fingerprint:
            self._fingerprint_index[fingerprint] = candidate["id"]

    def _remove(self, candidate_id: str) -> dict[str, Any] | None:
        """Remove one candidate and its fingerprint index entry."""
        candidate = self._candidates.pop(candidate_id, None)
        if candidate:
            fingerprint = candidate.get("fingerprint")
            if isinstance(fingerprint, str) and self._fingerprint_index.get(fingerprint) == candidate_id:
                self._fingerprint_index.pop(fingerprint, None)
        return candidate

    def _restore_journal(self) -> None:
        """Replay the append-only mutation journal after loading its snapshot."""
        if not os.path.exists(self._journal_path):
            return
        try:
            with open(self._journal_path, encoding="utf-8") as journal_file:
                for line in journal_file:
                    try:
                        operation = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if operation.get("op") == "batch":
                        if "enabled" in operation:
                            self._enabled = bool(operation["enabled"])
                        for candidate in operation.get("candidates") or []:
                            self._upsert(candidate)
                        for candidate_id in operation.get("removals") or []:
                            if isinstance(candidate_id, str):
                                self._remove(candidate_id)
                    elif operation.get("op") == "set_enabled":
                        self._enabled = bool(operation.get("enabled", self._enabled))
                    elif operation.get("op") == "upsert":
                        for candidate in operation.get("candidates") or []:
                            self._upsert(candidate)
                    elif operation.get("op") == "remove":
                        candidate_id = operation.get("id")
                        if not isinstance(candidate_id, str):
                            continue
                        self._remove(candidate_id)
                    self._journal_entries += 1
        except Exception as exc:
            logger.warning("r4 candidate ledger journal restore failed: %s", exc)

    def _persist(self, operation: dict[str, Any] | None = None) -> None:
        """Append a mutation and periodically compact it into the JSON snapshot."""
        try:
            ensure_dir(os.path.dirname(self._state_path) or ".")
            if operation:
                with open(self._journal_path, "a", encoding="utf-8") as journal_file:
                    journal_file.write(json.dumps(operation, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
                    journal_file.write("\n")
                self._journal_entries += 1
            if (
                operation
                and self._journal_entries < R4_CANDIDATE_JOURNAL_COMPACT_ENTRIES
                and os.path.exists(self._state_path)
            ):
                return
            self._compact()
        except Exception as exc:
            logger.warning("r4 candidate ledger persist failed: %s", exc)

    def _queue_persist(
        self,
        candidate_ids: set[str] | None = None,
        removed_ids: set[str] | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Coalesce state changes and start the ledger's single journal writer."""
        with self._persistence_lock:
            if candidate_ids:
                self._pending_candidate_ids.update(candidate_ids)
            if removed_ids:
                self._pending_removals.update(removed_ids)
                self._pending_candidate_ids.difference_update(removed_ids)
            if enabled is not None:
                self._pending_enabled = enabled
            if self._persist_thread is None:
                self._persist_thread = threading.Thread(
                    target=self._drain_persistence,
                    daemon=True,
                    name="r4-candidate-persist",
                )
                self._persist_thread.start()

    def _drain_persistence(self) -> None:
        """Flush coalesced journal operations without holding the state lock for I/O."""
        while True:
            with self._persistence_lock:
                if not self._pending_candidate_ids and not self._pending_removals and self._pending_enabled is None:
                    self._persist_thread = None
                    return
                candidate_ids = sorted(self._pending_candidate_ids)
                removed_ids = sorted(self._pending_removals)
                enabled = self._pending_enabled
                self._pending_candidate_ids.clear()
                self._pending_removals.clear()
                self._pending_enabled = None
            try:
                self._persist_batch(candidate_ids, removed_ids, enabled)
            except Exception as exc:
                logger.warning("r4 candidate ledger background persist failed: %s", exc)

    def _persist_batch(self, candidate_ids: list[str], removed_ids: list[str], enabled: bool | None) -> None:
        """Capture a consistent changed-record snapshot and append one journal operation."""
        with self._lock:
            candidates = [
                self._copy(self._candidates[candidate_id])
                for candidate_id in candidate_ids
                if candidate_id in self._candidates
            ]
        operation: dict[str, Any] = {"op": "batch"}
        if enabled is not None:
            operation["enabled"] = enabled
        if candidates:
            operation["candidates"] = candidates
        if removed_ids:
            operation["removals"] = removed_ids
        if len(operation) > 1:
            self._persist(operation)

    def _compact(self) -> None:
        """Write a complete snapshot and clear the replay journal."""
        with self._lock:
            payload = {
                "schema_version": R4_CANDIDATE_SCHEMA_VERSION,
                "enabled": self._enabled,
                "candidates": [self._copy(candidate) for candidate in self._candidates.values()],
            }
        temporary_path = f"{self._state_path}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as state_file:
            json.dump(payload, state_file, ensure_ascii=True, indent=2, sort_keys=True)
        os.replace(temporary_path, self._state_path)
        with suppress(FileNotFoundError):
            os.remove(self._journal_path)
        self._journal_entries = 0

    def _archive(self, candidate: dict[str, Any]) -> bool:
        """Append an evicted candidate to the lossless archive."""
        try:
            ensure_dir(os.path.dirname(self._archive_path) or ".")
            archived = dict(candidate)
            archived["archived_at"] = time.time()
            with open(self._archive_path, "a", encoding="utf-8") as archive_file:
                archive_file.write(json.dumps(archived, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
                archive_file.write("\n")
            return True
        except Exception as exc:
            logger.warning("r4 candidate archive failed: %s", exc)
            return False

    def _enforce_capacity(self) -> str | None:
        """Archive the oldest low-value candidates before growing the live ledger."""
        if len(self._candidates) < R4_CANDIDATE_MAX_RECORDS:
            return None
        candidate = min(
            (candidate for candidate in self._candidates.values() if candidate.get("state") in {"retired", "observed"}),
            key=lambda item: item.get("updated_at", 0.0),
            default=None,
        )
        if candidate is None:
            return None
        if not self._archive(candidate):
            return None
        candidate_id = str(candidate["id"])
        self._remove(candidate_id)
        return candidate_id

    @staticmethod
    def _fingerprint(record: dict[str, Any], source: str, binding: dict[str, list[str]]) -> str:
        identity = {
            "source": source,
            "entry_type": str(record.get("entry_type") or "note"),
            "binding": binding,
            "tags": sorted(tag for tag in (record.get("tags") or []) if isinstance(tag, str)),
        }
        encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:R4_CANDIDATE_FINGERPRINT_LENGTH]

    @staticmethod
    def _evidence(record: dict[str, Any], source: str) -> CandidateEvidence:
        entry_id = str(record.get("entry_id") or record.get("id") or "")
        content = str(record.get("content") or "")
        evidence_id = entry_id or hashlib.sha256(content.encode("utf-8")).hexdigest()[:R4_CANDIDATE_FINGERPRINT_LENGTH]
        return {
            "id": evidence_id,
            "source": source,
            "entry_id": entry_id,
            "trace_id": str(record.get("trace_id") or ""),
            "card_id": str(record.get("card_id") or ""),
            "summary": content[:R4_CANDIDATE_EVIDENCE_SUMMARY_MAX],
            "recorded_at": time.time(),
        }

    def submit_records(
        self,
        records: list[CandidateRecord] | list[dict[str, Any]],
        source: str = "refined_memory",
        binding: CandidateBinding | dict[str, Any] | None = None,
    ) -> CandidateCollectionResult:
        """Accumulate refined evidence without publishing a skill."""
        submitted: list[CandidateSnapshot] = []
        changed: set[str] = set()
        removed: set[str] = set()
        capacity_limited = False
        with self._lock:
            if not self._enabled:
                return {"success": True, "candidates": [], "submitted": 0, "reason": "candidate collection disabled"}
            for record in records:
                if not isinstance(record, dict):
                    continue
                normalized_binding = normalize_binding(binding or record.get("binding"), record)
                fingerprint = self._fingerprint(record, source, normalized_binding)
                candidate_id = self._fingerprint_index.get(fingerprint)
                candidate = self._candidates.get(candidate_id) if candidate_id else None
                now = time.time()
                if candidate is None:
                    evicted_id = self._enforce_capacity()
                    if evicted_id:
                        removed.add(evicted_id)
                    if len(self._candidates) >= R4_CANDIDATE_MAX_RECORDS:
                        capacity_limited = True
                        continue
                    candidate_id = f"{R4_CANDIDATE_ID_PREFIX}{uuid.uuid4().hex}"
                    candidate = {
                        "id": candidate_id,
                        "fingerprint": fingerprint,
                        "state": "observed",
                        "binding": normalized_binding,
                        "evidence": [],
                        "validation": {"valid": False, "reasons": ["awaiting evidence"]},
                        "skill_name": "",
                        "created_at": now,
                        "updated_at": now,
                    }
                    self._upsert(candidate)
                evidence = self._evidence(record, source)
                if evidence["id"] not in {item.get("id") for item in candidate["evidence"]}:
                    candidate["evidence"].append(evidence)
                    candidate["evidence"] = candidate["evidence"][-R4_CANDIDATE_MAX_EVIDENCE:]
                    candidate["updated_at"] = now
                    changed.add(candidate["id"])
                submitted.append(self._copy(candidate))
        if changed or removed:
            self._queue_persist(changed, removed)
        result: CandidateCollectionResult = {"success": True, "candidates": submitted, "submitted": len(submitted)}
        if capacity_limited:
            result["reason"] = "candidate ledger capacity reached"
            result["capacity_limited"] = True
        return result

    def validate(self, candidate_id: str) -> CandidateResult:
        """Validate the evidence threshold before candidate publication."""
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                return {"success": False, "error": f"candidate not found: {candidate_id}"}
            if candidate["state"] == "retired":
                return {"success": False, "error": "retired candidate cannot be validated"}
            reasons: list[str] = []
            if len(candidate["evidence"]) < R4_CANDIDATE_MIN_EVIDENCE:
                reasons.append(f"requires {R4_CANDIDATE_MIN_EVIDENCE} evidence records")
            if not candidate["binding"].get("postures"):
                reasons.append("requires at least one valid posture")
            valid = not reasons
            candidate["validation"] = {"valid": valid, "reasons": reasons}
            if valid and candidate["state"] == "observed":
                candidate["state"] = "validated"
            candidate["updated_at"] = time.time()
            result: CandidateResult = {"success": valid, "candidate": self._copy(candidate), "reasons": reasons}
        self._queue_persist({candidate_id})
        return result

    def transition(self, candidate_id: str, state: str, skill_name: str = "") -> CandidateResult:
        """Advance a validated candidate through its controlled lifecycle."""
        error = "" if state in R4_CANDIDATE_STATES else f"invalid candidate state: {state}"
        with self._lifecycle_lock:
            with self._lock:
                candidate = self._candidates.get(candidate_id)
                if candidate is None and not error:
                    error = f"candidate not found: {candidate_id}"
                if candidate and not error and state not in R4_CANDIDATE_STATE_TRANSITIONS.get(candidate["state"], ()):
                    error = f"invalid candidate transition: {candidate['state']} -> {state}"
                if candidate and state == "validated" and not candidate.get("validation", {}).get("valid"):
                    error = "candidate must pass validation before entering validated state"
                if candidate and state in ("canary", "active") and not candidate.get("validation", {}).get("valid"):
                    error = "candidate must validate before publication"
                if candidate and state == "active" and candidate["state"] != "canary":
                    error = "candidate must enter canary before activation"
                if candidate and state in ("canary", "active") and not skill_name and not candidate.get("skill_name"):
                    error = "published candidate requires a skill name"
                if error:
                    return {"success": False, "error": error}
                assert candidate is not None
                candidate["state"] = state
                if skill_name:
                    candidate["skill_name"] = skill_name
                candidate["updated_at"] = time.time()
                result: CandidateResult = {"success": True, "candidate": self._copy(candidate)}
        self._queue_persist({candidate_id})
        return result

    def get(self, candidate_id: str) -> CandidateSnapshot | None:
        """Return one candidate snapshot by id."""
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            return self._copy(candidate) if candidate else None

    def list(self, state: CandidateState | str = "") -> list[CandidateSnapshot]:
        """Return candidate snapshots ordered by their most recent update."""
        with self._lock:
            candidates = [
                candidate for candidate in self._candidates.values() if not state or candidate["state"] == state
            ]
            return [
                self._copy(candidate)
                for candidate in sorted(candidates, key=lambda item: item["updated_at"], reverse=True)
            ]

    @staticmethod
    def _copy(candidate: dict[str, Any]) -> CandidateSnapshot:
        return cast(CandidateSnapshot, json.loads(json.dumps(candidate)))

    def flush(self) -> None:
        """Wait until all queued journal writes for this store are complete."""
        with self._persistence_lock:
            worker = self._persist_thread
        if worker and worker is not threading.current_thread():
            worker.join()

    def close(self) -> None:
        """Drain queued persistence before releasing this store instance."""
        self.flush()


class R4CandidateAdapter(CandidateLedgerPort):
    """Adapt the R4 candidate ledger to the L1 port boundary."""

    def __init__(self, store: CandidateStore | None = None) -> None:
        self._store = store

    def _candidate_store(self) -> CandidateStore:
        return self._store or get_candidate_store()

    def submit_records(
        self,
        records: list[CandidateRecord],
        source: str = "refined_memory",
        binding: CandidateBinding | None = None,
    ) -> CandidateCollectionResult:
        """Accumulate portable evidence through the candidate ledger port."""
        return self._candidate_store().submit_records(records, source=source, binding=binding)

    def list_candidates(self, state: CandidateState | str = "") -> list[CandidateSnapshot]:
        """List candidate snapshots filtered by lifecycle state."""
        return self._candidate_store().list(state=state)

    def get_candidate(self, candidate_id: str) -> CandidateSnapshot | None:
        """Return one candidate snapshot by identifier."""
        return self._candidate_store().get(candidate_id)

    def status(self) -> CandidateStatus:
        """Return collection policy and lifecycle counts."""
        return self._candidate_store().status()

    def set_enabled(self, enabled: bool) -> CandidateStatus:
        """Set candidate collection without removing existing evidence."""
        result = self._candidate_store().set_enabled(enabled)
        try:
            from l3.config.settings_center import get_center

            get_center().set_l2("skill.candidate_enabled", bool(enabled))
        except Exception as exc:
            logger.debug("r4 candidate adapter settings mirror skipped: %s", exc)
        return result

    def validate(self, candidate_id: str) -> CandidateResult:
        """Validate a candidate's accumulated evidence."""
        return self._candidate_store().validate(candidate_id)

    def publish(self, candidate_id: str, intent: str, scope: str = "") -> CandidateResult:
        """Publish a validated candidate as a scoped canary skill."""
        return publish_candidate(candidate_id, intent, scope=scope)

    def activate(self, candidate_id: str) -> CandidateResult:
        """Promote a canary candidate and its bound skill."""
        return activate_candidate(candidate_id)

    def retire(self, candidate_id: str) -> CandidateResult:
        """Retire a candidate and remove its skill from injection."""
        return retire_candidate(candidate_id)


_store: CandidateStore | None = None
_store_lock = threading.RLock()


def get_candidate_store() -> CandidateStore:
    """Return the process-wide R4 candidate ledger."""
    global _store
    with _store_lock:
        if _store is None:
            _store = CandidateStore()
        return _store


def reset_candidate_store() -> None:
    """Reset the candidate ledger singleton for test isolation."""
    global _store
    with _store_lock:
        store = _store
        if store is not None:
            store.close()
        _store = None


def get_candidate_ledger() -> CandidateLedgerPort:
    """Resolve the swappable candidate-ledger port with a local fallback."""
    from l1.kernel.ports import get_port

    try:
        return cast(CandidateLedgerPort, get_port("r4_candidates"))
    except KeyError:
        return R4CandidateAdapter()


def _publication_error(validation: dict[str, Any], intent: str) -> str:
    """Return the first publication precondition that is not satisfied."""
    if not validation.get("success"):
        reasons = validation.get("reasons") or []
        return "; ".join(str(reason) for reason in reasons) or str(validation.get("error") or "validation failed")
    candidate = validation.get("candidate") or {}
    binding = candidate.get("binding") or {}
    if not any(binding.get(key) for key in ("cell_ids", "roles", "agent_ids", "card_natures")):
        return "candidate requires an explicit canary binding target"
    if not intent.strip():
        return "intent required to publish a candidate"
    return ""


def publish_candidate(candidate_id: str, intent: str, scope: str = "") -> dict[str, Any]:
    """Generate a bound canary skill from a validated candidate."""
    candidate_store = get_candidate_store()
    # The ledger and skill registry must advance together. The ledger lock
    # stays scoped to CandidateStore methods, even while R4 generation runs.
    with candidate_store._lifecycle_lock:
        current = candidate_store.get(candidate_id)
        if current and current.get("state") in ("canary", "active"):
            return {
                "success": False,
                "error": f"candidate already published in {current['state']} state",
                "candidate": current,
            }
        validation = candidate_store.validate(candidate_id)
        error = _publication_error(validation, intent)
        if error:
            return {"success": False, "error": error, "validation": validation}
        candidate = validation["candidate"]
        binding = candidate.get("binding") or {}
        try:
            from l3.memory.r4_agent import get_r4_agent

            cell_ids = binding.get("cell_ids") or []
            evolved = get_r4_agent().evolve_skill(
                intent=intent,
                cell_id=cell_ids[0] if cell_ids else "",
                scope=scope,
                binding=binding,
                status="canary",
            )
        except Exception as exc:
            logger.warning("r4 candidate publish failed: %s", exc)
            return {"success": False, "error": str(exc)}
        if not evolved.get("success"):
            return evolved
        transition = candidate_store.transition(candidate_id, "canary", skill_name=str(evolved.get("skill") or ""))
        if not transition.get("success"):
            return transition
        return {"success": True, "candidate": transition["candidate"], "skill": evolved}


def activate_candidate(candidate_id: str) -> dict[str, Any]:
    """Promote a canary candidate and its skill to active injection."""
    candidate_store = get_candidate_store()
    with candidate_store._lifecycle_lock:
        candidate = candidate_store.get(candidate_id)
        if candidate is None:
            return {"success": False, "error": f"candidate not found: {candidate_id}"}
        if candidate.get("state") != "canary":
            return {"success": False, "error": "candidate must be canary before activation"}
        skill_name = str(candidate.get("skill_name") or "")
        try:
            from l1.kernel.skill import get_skill_manager

            updated = get_skill_manager().update(skill_name, {"status": "active"}, internal=True)
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        if not updated.get("success"):
            return updated
        return candidate_store.transition(candidate_id, "active")


def retire_candidate(candidate_id: str) -> dict[str, Any]:
    """Retire a candidate and remove its published skill from injection."""
    candidate_store = get_candidate_store()
    with candidate_store._lifecycle_lock:
        candidate = candidate_store.get(candidate_id)
        if candidate is None:
            return {"success": False, "error": f"candidate not found: {candidate_id}"}
        skill_name = str(candidate.get("skill_name") or "")
        if skill_name:
            try:
                from l1.kernel.skill import get_skill_manager

                updated = get_skill_manager().update(skill_name, {"status": "retired"}, internal=True)
            except Exception as exc:
                return {"success": False, "error": str(exc)}
            if not updated.get("success"):
                return updated
        return candidate_store.transition(candidate_id, "retired")
