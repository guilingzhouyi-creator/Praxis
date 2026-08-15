"""Port types — shared value types used across port interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

CandidateState = Literal["observed", "validated", "canary", "active", "retired"]


class CandidateBinding(TypedDict):
    """Adapter-neutral target binding for an R4 candidate."""

    cell_ids: list[str]
    roles: list[str]
    agent_ids: list[str]
    card_natures: list[str]
    postures: list[str]


class CandidateSnapshot(TypedDict, total=False):
    """Serialized candidate record crossing the kernel port boundary."""

    id: str
    fingerprint: str
    state: CandidateState
    binding: CandidateBinding
    evidence: list[dict[str, Any]]
    validation: dict[str, Any]
    skill_name: str
    created_at: float
    updated_at: float


class CandidateStatus(TypedDict):
    """Serialized candidate collection status."""

    enabled: bool
    counts: dict[CandidateState, int]


class CandidateResult(TypedDict, total=False):
    """Serialized result shared by candidate ledger adapters."""

    success: bool
    error: str
    reason: str
    candidate: CandidateSnapshot
    candidates: list[CandidateSnapshot]
    submitted: int
    validation: dict[str, Any]
    skill: dict[str, Any]


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
