"""Persistent candidate ledger for evidence-backed R4 skill evolution."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from typing import Any

from l1.kernel.params.agent import (
    R4_CANDIDATE_ENABLED_DEFAULT,
    R4_CANDIDATE_EVIDENCE_SUMMARY_MAX,
    R4_CANDIDATE_FINGERPRINT_LENGTH,
    R4_CANDIDATE_ID_PREFIX,
    R4_CANDIDATE_MAX_EVIDENCE,
    R4_CANDIDATE_MIN_EVIDENCE,
    R4_CANDIDATE_SCHEMA_VERSION,
    R4_CANDIDATE_STATE_FILE,
)
from l1.kernel.params.system import SKILL_POSTURE_DEFAULT, SKILL_POSTURE_VALID
from l1.kernel.paths import get_paths
from l1.kernel.platform import ensure_dir
from l1.kernel.ports import CandidateLedgerPort

logger = logging.getLogger(__name__)

_CANDIDATE_STATES = frozenset({"observed", "validated", "canary", "active", "retired"})


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
        self._state_path = state_path or os.path.join(get_paths().data_dir, R4_CANDIDATE_STATE_FILE)
        self._enabled = R4_CANDIDATE_ENABLED_DEFAULT
        self._candidates: dict[str, dict[str, Any]] = {}
        self._restore()

    def status(self) -> dict[str, Any]:
        """Return candidate collection state and lifecycle counts."""
        with self._lock:
            counts = {state: 0 for state in _CANDIDATE_STATES}
            for candidate in self._candidates.values():
                state = candidate.get("state")
                if state in counts:
                    counts[state] += 1
            return {"enabled": self._enabled, "counts": counts}

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        """Enable or disable candidate collection without clearing evidence."""
        with self._lock:
            self._enabled = bool(enabled)
            return self.status()

    def _restore(self) -> None:
        if not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, encoding="utf-8") as state_file:
                data = json.load(state_file)
            if data.get("schema_version") != R4_CANDIDATE_SCHEMA_VERSION:
                logger.warning("r4 candidate ledger schema mismatch: %s", self._state_path)
                return
            candidates = data.get("candidates") or []
            self._candidates = {
                candidate["id"]: candidate
                for candidate in candidates
                if isinstance(candidate, dict) and isinstance(candidate.get("id"), str)
            }
        except Exception as exc:
            logger.warning("r4 candidate ledger restore failed: %s", exc)

    def _persist(self) -> None:
        try:
            ensure_dir(os.path.dirname(self._state_path) or ".")
            payload = {
                "schema_version": R4_CANDIDATE_SCHEMA_VERSION,
                "candidates": list(self._candidates.values()),
            }
            temporary_path = f"{self._state_path}.tmp"
            with open(temporary_path, "w", encoding="utf-8") as state_file:
                json.dump(payload, state_file, ensure_ascii=True, indent=2, sort_keys=True)
            os.replace(temporary_path, self._state_path)
        except Exception as exc:
            logger.warning("r4 candidate ledger persist failed: %s", exc)

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
    def _evidence(record: dict[str, Any], source: str) -> dict[str, Any]:
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
        records: list[dict[str, Any]],
        source: str = "refined_memory",
        binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Accumulate refined evidence without publishing a skill."""
        submitted: list[dict[str, Any]] = []
        with self._lock:
            if not self._enabled:
                return {"success": True, "candidates": [], "submitted": 0, "reason": "candidate collection disabled"}
            for record in records:
                if not isinstance(record, dict):
                    continue
                normalized_binding = normalize_binding(binding or record.get("binding"), record)
                fingerprint = self._fingerprint(record, source, normalized_binding)
                candidate = next(
                    (item for item in self._candidates.values() if item.get("fingerprint") == fingerprint), None
                )
                now = time.time()
                if candidate is None:
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
                    self._candidates[candidate_id] = candidate
                evidence = self._evidence(record, source)
                if evidence["id"] not in {item.get("id") for item in candidate["evidence"]}:
                    candidate["evidence"].append(evidence)
                    candidate["evidence"] = candidate["evidence"][-R4_CANDIDATE_MAX_EVIDENCE:]
                    candidate["updated_at"] = now
                submitted.append(self._copy(candidate))
            if submitted:
                self._persist()
        return {"success": True, "candidates": submitted, "submitted": len(submitted)}

    def validate(self, candidate_id: str) -> dict[str, Any]:
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
            self._persist()
            return {"success": valid, "candidate": self._copy(candidate), "reasons": reasons}

    def transition(self, candidate_id: str, state: str, skill_name: str = "") -> dict[str, Any]:
        """Advance a validated candidate through its controlled lifecycle."""
        error = "" if state in _CANDIDATE_STATES else f"invalid candidate state: {state}"
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None and not error:
                error = f"candidate not found: {candidate_id}"
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
            self._persist()
            return {"success": True, "candidate": self._copy(candidate)}

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        """Return one candidate snapshot by id."""
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            return self._copy(candidate) if candidate else None

    def list(self, state: str = "") -> list[dict[str, Any]]:
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
    def _copy(candidate: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(candidate))


class R4CandidateAdapter(CandidateLedgerPort):
    """Adapt the R4 candidate ledger to the L1 port boundary."""

    def __init__(self, store: CandidateStore | None = None) -> None:
        self._store = store

    def _candidate_store(self) -> CandidateStore:
        return self._store or get_candidate_store()

    def list_candidates(self, state: str = "") -> list[dict]:
        """List candidate snapshots filtered by lifecycle state."""
        return self._candidate_store().list(state=state)

    def get_candidate(self, candidate_id: str) -> dict | None:
        """Return one candidate snapshot by identifier."""
        return self._candidate_store().get(candidate_id)

    def status(self) -> dict:
        """Return collection policy and lifecycle counts."""
        return self._candidate_store().status()

    def set_enabled(self, enabled: bool) -> dict:
        """Set candidate collection without removing existing evidence."""
        result = self._candidate_store().set_enabled(enabled)
        try:
            from l3.config.settings_center import get_center

            get_center().set_l2("skill.candidate_enabled", bool(enabled))
        except Exception as exc:
            logger.debug("r4 candidate adapter settings mirror skipped: %s", exc)
        return result

    def validate(self, candidate_id: str) -> dict:
        """Validate a candidate's accumulated evidence."""
        return self._candidate_store().validate(candidate_id)

    def publish(self, candidate_id: str, intent: str, scope: str = "") -> dict:
        """Publish a validated candidate as a scoped canary skill."""
        return publish_candidate(candidate_id, intent, scope=scope)

    def activate(self, candidate_id: str) -> dict:
        """Promote a canary candidate and its bound skill."""
        return activate_candidate(candidate_id)

    def retire(self, candidate_id: str) -> dict:
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
        _store = None


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
