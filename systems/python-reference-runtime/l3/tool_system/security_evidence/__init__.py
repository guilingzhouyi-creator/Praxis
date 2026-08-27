"""Security evidence chain — public package surface.

Module layout:
  models.py — decision vocabulary, ChainRecord / EvidencePoint, hashing
  facade.py — module-level singleton + never-raising entry bridges
  core.py   — SecurityEvidence collector (record / query / analyze / report)

This ``__init__`` re-exports the collector, the singleton entry points and
the decision vocabulary so all existing call sites
(``from l3.tool_system.security_evidence import record_evidence``) keep
working unchanged.
"""

from __future__ import annotations

from .core import (  # noqa: F401 — re-export for callers
    EVIDENCE_CHAIN_ID_PREFIX,
    SecurityEvidence,
    ensure_listener,
    get_evidence,
    record_evidence,
    record_from_metric,
    reset_evidence,
)
from .models import (  # noqa: F401 — re-export for callers
    DECISION_ALLOW,
    DECISION_AUTO_APPROVED,
    DECISION_BLOCK,
    DECISION_BYPASS,
    DECISION_CHANGE,
    DECISION_FULL_POWER,
    DECISION_WARN,
    VERDICT_BYPASSED,
    VERDICT_CLEAN,
    VERDICT_WARRANTED,
    ChainRecord,
    EvidencePoint,
)

__all__ = [
    "SecurityEvidence",
    "ChainRecord",
    "EvidencePoint",
    "DECISION_ALLOW",
    "DECISION_AUTO_APPROVED",
    "DECISION_BLOCK",
    "DECISION_BYPASS",
    "DECISION_CHANGE",
    "DECISION_FULL_POWER",
    "DECISION_WARN",
    "VERDICT_BYPASSED",
    "VERDICT_CLEAN",
    "VERDICT_WARRANTED",
    "get_evidence",
    "reset_evidence",
    "record_evidence",
    "record_from_metric",
    "ensure_listener",
]
