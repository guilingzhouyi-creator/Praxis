"""Security evidence — data model layer.

Extracted from ``security_evidence.py``: the decision vocabulary, the
ChainRecord / EvidencePoint dataclasses, the row fixity hashing and the
raw-bounding / row-rebuild helpers used by the collector.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.system import (
    EVIDENCE_CHAIN_HASH_TRUNC,
    EVIDENCE_CHAIN_RAW_MAX,
)

# Decision vocabulary shared by the whole evidence surface (stable strings).
DECISION_CHANGE = "CHANGE"  # posture / policy / harness switched
DECISION_ALLOW = "ALLOW"  # offensive capability granted, nature-authorized
DECISION_BYPASS = "BYPASS"  # gate bypassed via a soft switch (policy disabled)
DECISION_BLOCK = "BLOCK"  # gate refused the request
DECISION_WARN = "WARN"  # confirmation required / warning issued
DECISION_FULL_POWER = "FULL_POWER"  # G4 escalated a high-danger tool via posture
DECISION_AUTO_APPROVED = "AUTO_APPROVED"  # G4 approved via a downgraded harness

VERDICT_CLEAN = "clean"
VERDICT_WARRANTED = "warranted"
VERDICT_BYPASSED = "bypassed"

# Metric names (security.*) -> (phase, gate, decision) — the L1 metric sink
# is the choke point for gatechain/constitution decisions that live in the
# kernel layer and cannot import L3 directly.
_METRIC_TO_EVIDENCE: dict[str, tuple[str, str, str]] = {
    "security.gate.g4.full_power": ("g4", "g4", DECISION_FULL_POWER),
    "security.gate.g4.auto_approved": ("g4", "g4", DECISION_AUTO_APPROVED),
    "security.gate.g4.blocked": ("g4", "g4", DECISION_BLOCK),
    "security.gate.skill_use.blocked": ("constitution", "posture_gate", DECISION_BLOCK),
}

DEFAULT_CHAIN_KIND = "ambient"


def _hash_row(fields: dict[str, Any]) -> tuple[str, str]:
    """Return (full sha256, truncated prefix) of a canonical evidence row.

    The fixity anchor covers every substantive field (ts, phase, gate,
    decision, target, source, tags, raw) — a tampered row fails verification.
    """
    payload = json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    full = hashlib.sha256(payload).hexdigest()
    return full, full[:EVIDENCE_CHAIN_HASH_TRUNC]


@dataclass
class ChainRecord:
    """An evidence chain — the correlated decision sequence of one posture event.

    ``kind`` mirrors why the chain was opened (attack / downgrade /
    policy-bypass / ambient); ``evidence_ids`` holds the ordered member ids;
    ``closed`` 0.0 means the chain is still open.
    """

    chain_id: str
    kind: str
    source: str = ""
    opened: float = field(default_factory=time.time)
    closed: float = 0.0
    reason: str = ""
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a plain dict (API surface)."""
        return {
            "chain_id": self.chain_id,
            "kind": self.kind,
            "source": self.source,
            "opened": self.opened,
            "closed": self.closed or None,
            "open": self.closed == 0,
            "reason": self.reason,
            "evidence": len(self.evidence_ids),
        }


@dataclass
class EvidencePoint:
    """A single evidence point inside a chain.

    ``raw`` is bounded (EVIDENCE_CHAIN_RAW_MAX chars); ``raw_size`` is the
    original payload byte size and ``raw_hash`` the full sha256 of the raw at
    record time — the fixity anchor (truncated prefix for display).
    """

    evidence_id: str
    chain_id: str
    ts: float
    phase: str
    gate: str
    decision: str
    target: str
    source: str
    tags: dict[str, str]
    raw: dict[str, Any]
    raw_size: int
    raw_hash: str
    hash_prefix: str

    def to_dict(self) -> dict:
        """Serialize to a plain dict (API / report payload)."""
        return {
            "evidence_id": self.evidence_id,
            "chain_id": self.chain_id,
            "ts": self.ts,
            "phase": self.phase,
            "gate": self.gate,
            "decision": self.decision,
            "target": self.target,
            "source": self.source,
            "tags": self.tags,
            "raw": self.raw,
            "raw_size": self.raw_size,
            "raw_hash": self.raw_hash,
            "hash_prefix": self.hash_prefix,
        }


def _bounded_raw(raw: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
    """Truncate a raw snapshot to EVIDENCE_CHAIN_RAW_MAX; returns
    (bounded dict, canonical byte size of the ORIGINAL raw)."""
    payload = json.dumps(raw or {}, sort_keys=True, ensure_ascii=False, default=str)
    size = len(payload.encode("utf-8"))
    if raw is None or size <= EVIDENCE_CHAIN_RAW_MAX:
        return (raw or {}), size
    return {"truncated": True, "snapshot": payload[:EVIDENCE_CHAIN_RAW_MAX] + "..."}, size


def _ev_from_dict(data: dict) -> EvidencePoint | None:
    """Rebuild an EvidencePoint from a persisted row (best-effort)."""
    try:
        return EvidencePoint(
            evidence_id=data.get("evidence_id", ""),
            chain_id=data.get("chain_id", ""),
            ts=float(data.get("ts", 0)),
            phase=data.get("phase", ""),
            gate=data.get("gate", ""),
            decision=data.get("decision", ""),
            target=data.get("target", ""),
            source=data.get("source", ""),
            tags=data.get("tags") or {},
            raw=data.get("raw") or {},
            raw_size=int(data.get("raw_size", 0)),
            raw_hash=data.get("raw_hash", ""),
            hash_prefix=data.get("hash_prefix", ""),
        )
    except Exception:
        return None
