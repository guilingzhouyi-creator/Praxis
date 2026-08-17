"""L3 domain ports — CardRegistryPort / MonitorBusPort / CandidateLedgerPort.

WS5.1 surface shrink: domain ports moved OUT of the kernel namespace so
the Rust kernel boundary only carries mechanism ports. Importers use
``from l3.ports import ...``; the kernel port registry name is unchanged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from l1.kernel.ports.types import (
    CandidateBinding,
    CandidateCollectionResult,
    CandidateRecord,
    CandidateResult,
    CandidateSnapshot,
    CandidateState,
    CandidateStatus,
)

# ── Card Registry Port ──


class CardRegistryPort(ABC):
    """Card type registry — query and install card definitions."""

    @abstractmethod
    def list_types(self) -> list[dict]:
        """List registered card type definitions."""

    @abstractmethod
    def install_def(self, cdef: dict, source: str = "") -> bool:
        """Install a card type definition; return success."""


# ── Monitor Bus Port ──


class MonitorBusPort(ABC):
    """Monitoring event bus — structured event emission and query."""

    @abstractmethod
    def emit(self, type_: str, source: str, severity: str, message: str, data: dict | None = None) -> None:
        """Emit a structured monitoring event."""

    @abstractmethod
    def query(
        self, type_prefix: str = "", severity: str = "", source: str = "", since: float = 0.0, limit: int = 100
    ) -> list[dict]:
        """Query recent monitoring events matching the filters."""


# ── R4 Candidate Ledger Port ──


class CandidateLedgerPort(ABC):
    """R4 evidence-candidate lifecycle with a serialized, Rust-friendly contract."""

    @abstractmethod
    def submit_records(
        self,
        records: list[CandidateRecord],
        source: str = "refined_memory",
        binding: CandidateBinding | None = None,
    ) -> CandidateCollectionResult: ...

    @abstractmethod
    def list_candidates(self, state: CandidateState | str = "") -> list[CandidateSnapshot]: ...

    @abstractmethod
    def get_candidate(self, candidate_id: str) -> CandidateSnapshot | None: ...

    @abstractmethod
    def status(self) -> CandidateStatus: ...

    @abstractmethod
    def set_enabled(self, enabled: bool) -> CandidateStatus: ...

    @abstractmethod
    def validate(self, candidate_id: str) -> CandidateResult: ...

    @abstractmethod
    def publish(self, candidate_id: str, intent: str, scope: str = "") -> CandidateResult: ...

    @abstractmethod
    def activate(self, candidate_id: str) -> CandidateResult: ...

    @abstractmethod
    def retire(self, candidate_id: str) -> CandidateResult: ...
