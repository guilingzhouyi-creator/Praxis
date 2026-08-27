"""Memory domain filter (Phase 3, M1) — identity-domain + Cell-domain gating.

Filters memory entries (R1-R4, including the R4 archive) produced by an
Agent entity or Cell domain before retrieval/re-injection: an entry is
only visible when its domain is allowed for the requesting identity/Cell.

Both switches are operator-controlled (API + L2 Shell), never hardcoded:

  enabled      — master switch (default off = no filtering)
  fine_grained — finer filtering down to identity sub-domains

Degrades gracefully: disabled → everything allowed; unbound identity →
only Cell-domain gating applies.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from l1.kernel.params.system import (
    MEMORY_FILTER_ENABLED_DEFAULT,
    MEMORY_FILTER_FINE_GRAINED_DEFAULT,
)

logger = logging.getLogger(__name__)

_filter_lock = threading.RLock()
_filter: MemoryDomainFilter | None = None


class MemoryDomainFilter:
    """Identity-domain / Cell-domain memory filtering with operator switches."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._enabled = MEMORY_FILTER_ENABLED_DEFAULT
        self._fine_grained = MEMORY_FILTER_FINE_GRAINED_DEFAULT

    # ── Operator switches ──

    def set_switches(self, enabled: bool | None = None, fine_grained: bool | None = None) -> dict:
        """Set the enable / fine-grained switches (API + L2 Shell)."""
        with self._lock:
            if enabled is not None:
                self._enabled = bool(enabled)
            if fine_grained is not None:
                self._fine_grained = bool(fine_grained)
        return {"success": True, "enabled": self._enabled, "fine_grained": self._fine_grained}

    def status(self) -> dict:
        """Current switch state."""
        with self._lock:
            return {"enabled": self._enabled, "fine_grained": self._fine_grained}

    # ── Filtering ──

    def is_allowed(
        self,
        entry: dict[str, Any],
        cell_id: str = "",
        role: str = "",
        scope: str = "",
        intent: str = "",
        domain: str = "",
    ) -> bool:
        """Decide whether a memory entry is visible to the requester.

        Identity is NOT a static role: Cell agents are peer entities whose
        active identity is driven by HTN-C task dispatch — ``match_identity``
        hits one of the generic build/test/review fields from the task
        intent. When ``intent`` is provided, the requester's allowed set is
        exactly that hit (an entry tagged with a different identity is
        invisible); otherwise the static binding resolution (or the full
        IDENTITY_DEFAULT_SET for unbound single-Cell composites) applies.

        Args:
            entry: Memory entry (has ``tags`` / ``cell_id`` / ``entry_type``).
            cell_id: Requester's Cell (identity domain source).
            role: Requester's role within the Cell.
            scope: Requester's memory scope (e.g. "l3a-c-1").
            intent: Driving task intent (HTN-C dispatch source, optional).
            domain: Optional card domain hint for identity matching.

        Returns:
            True when the entry may be retrieved. Disabled → always True.
        """
        with self._lock:
            enabled = self._enabled
            fine = self._fine_grained
        if not enabled:
            return True
        entry_tags = set(entry.get("tags") or [])
        entry_cell = entry.get("cell_id", "")
        # Cell-domain gate: an entry tagged with a different Cell scope is
        # invisible to a requester of another Cell. This boundary holds in
        # EVERY mode (coarse and fine alike) — fine-grained only adds the
        # identity gate on top, it never removes the Cell boundary.
        if entry_cell and cell_id and entry_cell != cell_id:
            return False
        if not fine:
            return True
        # Identity-domain gate: the allowed set is either the HTN-C hit on
        # the driving intent (peer agents, identity by dispatch) or the
        # static binding resolution (narrowed by domain_tags; unbound →
        # full IDENTITY_DEFAULT_SET for single-Cell composite entities).
        allowed: set[str] = set()
        try:
            if intent or domain:
                from l3.bus.htn_planner import match_identity

                hit = match_identity(intent, domain=domain)
                if hit:
                    allowed = {hit}
            if not allowed:
                from l1.kernel.identity_binding import get_identity_binding_manager

                allowed = set(get_identity_binding_manager().identity_set_for(cell_id or "", role or ""))
        except Exception as e:
            logger.debug("memory_domain_filter: identity resolve skipped: %s", e)
            allowed = set()
        return not (allowed and not (entry_tags & allowed))

    def filter_entries(
        self,
        entries: list[dict[str, Any]],
        cell_id: str = "",
        role: str = "",
        scope: str = "",
        intent: str = "",
        domain: str = "",
    ) -> list[dict[str, Any]]:
        """Filter a list of entries in place of retrieval (R1-R4 inclusive)."""
        if not self._enabled:
            return entries
        return [
            e
            for e in entries
            if self.is_allowed(e, cell_id=cell_id, role=role, scope=scope, intent=intent, domain=domain)
        ]


def get_memory_filter() -> MemoryDomainFilter:
    """Get the global MemoryDomainFilter singleton."""
    global _filter
    with _filter_lock:
        if _filter is None:
            _filter = MemoryDomainFilter()
        return _filter


def reset_memory_filter() -> None:
    """Reset the singleton (used by tests)."""
    global _filter
    with _filter_lock:
        _filter = None
