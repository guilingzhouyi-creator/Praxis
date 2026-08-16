"""Port types — shared value types used across port interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

CandidateState = Literal["observed", "validated", "canary", "active", "retired"]
InputActivityState = Literal["active", "idle", "unknown"]


class CandidateBinding(TypedDict):
    """Adapter-neutral target binding for an R4 candidate."""

    cell_ids: list[str]
    roles: list[str]
    agent_ids: list[str]
    card_natures: list[str]
    postures: list[str]


class CandidateEvidence(TypedDict):
    """One normalized evidence item attached to a candidate."""

    id: str
    source: str
    entry_id: str
    trace_id: str
    card_id: str
    summary: str
    recorded_at: float


class CandidateValidation(TypedDict):
    """Validation verdict persisted with a candidate snapshot."""

    valid: bool
    reasons: list[str]


class CandidateRecord(TypedDict, total=False):
    """Portable evidence input accepted by a candidate ledger adapter."""

    id: str
    entry_id: str
    entry_type: str
    cell_id: str
    role: str
    agent_id: str
    tags: list[str]
    posture: str
    binding: CandidateBinding
    trace_id: str
    card_id: str
    content: str


class CandidateSnapshot(TypedDict, total=False):
    """Serialized candidate record crossing the kernel port boundary."""

    id: str
    fingerprint: str
    state: CandidateState
    binding: CandidateBinding
    evidence: list[CandidateEvidence]
    validation: CandidateValidation
    skill_name: str
    created_at: float
    updated_at: float


class CandidateStatus(TypedDict):
    """Serialized candidate collection status."""

    enabled: bool
    counts: dict[CandidateState, int]


class CandidateCollectionResult(TypedDict, total=False):
    """Serialized evidence-ingestion result from a candidate ledger."""

    success: bool
    candidates: list[CandidateSnapshot]
    submitted: int
    reason: str
    capacity_limited: bool


class CandidateSkillResult(TypedDict, total=False):
    """Serialized result returned by the skill-generation boundary."""

    success: bool
    error: str
    skill: str


class CandidateResult(TypedDict, total=False):
    """Serialized result shared by candidate ledger adapters."""

    success: bool
    error: str
    reason: str
    candidate: CandidateSnapshot
    candidates: list[CandidateSnapshot]
    submitted: int
    reasons: list[str]
    validation: CandidateResult
    skill: CandidateSkillResult


@dataclass
class InputActivitySnapshot:
    """Privacy-preserving aggregate of keyboard/pointer activity."""

    state: InputActivityState = "unknown"
    keyboard_active: bool = False
    pointer_active: bool = False
    last_activity_at: float = 0.0
    idle_seconds: float = 0.0
    source: str = "noop"
    permission: str = "unavailable"


@dataclass
class Endpoint:
    """Transport endpoint — abstract address, not tied to TCP (host, port)."""

    address: str = ""
    hint: str = "tcp"


@dataclass
class Result:
    """Generic success/failure result — no exception leak across port boundaries."""

    success: bool = True
    error: str = ""
    data: dict = field(default_factory=dict)

    @staticmethod
    def ok(**data: Any) -> Result:
        """Build a success Result carrying optional *data*."""
        return Result(success=True, data=data)

    @staticmethod
    def fail(msg: str, **data: Any) -> Result:
        """Build a failure Result with *msg* and optional *data*."""
        return Result(success=False, error=msg, data=data)


@dataclass
class Message:
    """Domain message — locale-aware, adapter-neutral serialization."""

    type: str = "message"
    source: str = ""
    target: str = ""
    payload: Any = None
    timestamp: float = 0.0
    locale: str = "en"
    headers: dict = field(default_factory=dict)


@dataclass
class Event:
    """Domain event — carry pre-localized message for multi-lingual consumers."""

    type: str = ""
    source: str = ""
    severity: str = "info"
    message: str = ""
    message_locale: str = ""
    data: dict = field(default_factory=dict)
