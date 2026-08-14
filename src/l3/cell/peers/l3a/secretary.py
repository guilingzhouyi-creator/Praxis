"""L3A-C secretary — capability-threshold upgrade from assist to peer.

Phase 4 of the organizational-evolution design (see ``docs/design/
related-work.md``): the L3A-C secretary undertakes analysis/reporting and
collaborative card production in subordinate ("assist") mode. Each
successful contribution advances its capability score; reaching
``L3AC_CAPABILITY_THRESHOLD`` upgrades it to egalitarian ("peer") mode,
where L3A operates as an intent-decision hub commissioning the secretary
as a peer collaborator instead of a subordinate.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

from l3.error_bus import capture

from . import params as _p

logger = logging.getLogger(__name__)


class L3ACSecretary:
    """L3A-C secretary — tracks contributions and assist→peer upgrades."""

    def __init__(self, threshold: int = 0) -> None:
        self._threshold = threshold or _p.L3AC_CAPABILITY_THRESHOLD
        self._score = 0
        self._contributions: deque[dict] = deque(maxlen=_p.L3AC_HISTORY_MAX)
        self._lock = threading.RLock()
        # phase2d: memory scope + peer session (D1/M1-B)
        self._scope: str = "l3a"  # memory scope; evolved secretaries get "l3a-c-<n>"
        self._peer_session_id: str = ""  # background session spawned on upgrade (D1)
        # main (l3ac-toggles): operator-controllable switches (not code-embedded)
        self._enabled_override: bool | None = None  # API-set toggle (None = settings default)
        self._mode_override: str | None = None  # API-pinned mode (None = score-driven)

    def contribute(self, kind: str, success: bool, card_id: str = "", detail: str = "") -> dict:
        """Record a secretary contribution (analysis/report/card production).

        Success advances the capability score by 1, failure retreats it
        (bounded at 0); crossing the threshold upgrades assist → peer.
        Returns the post-update status including whether this contribution
        caused the upgrade.
        """
        with self._lock:
            delta = 1 if success else -1
            prev = self._score
            self._score = max(0, self._score + delta)
            self._contributions.append(
                {
                    "kind": kind,
                    "success": success,
                    "card_id": card_id,
                    "detail": detail,
                    "at": time.time(),
                }
            )
            upgraded = self._score >= self._threshold > prev
        logger.info("l3a secretary: contribution kind=%s success=%s score=%d", kind, success, self._score)
        # D1: crossing the threshold spawns the secretary's own background
        # session (peer mode = real egalitarian entity with its own memory
        # scope). Idempotent — only the first upgrade spawns.
        peer_session_id = ""
        if upgraded:
            peer_session_id = self._spawn_peer_session()
        # M2-B: persist the contribution into the secretary's OWN memory
        # scope (R1-R3) + R5 graph edge (non-blocking, degrades off).
        entry_id = self._persist_contribution(kind, success, card_id)
        return {
            "recorded": True,
            "kind": kind,
            "score": self._score,
            "mode": self.mode(),
            "upgraded": upgraded,
            "peer_session_id": peer_session_id,
            "memory_entry_id": entry_id,
            "contribution_success": success,
        }

    def _identity_tags(self) -> list[str]:
        """Resolve the secretary's identity set for memory tagging (B5c).

        Links the memory scope to the identity system: the secretary's
        generic three-identity set (build/test/review, narrowed by binding
        domain_tags) becomes memory tags, so recalled entries carry the
        identity domain. Degrades to [] when unbound.
        """
        try:
            from l1.kernel.identity_binding import get_identity_binding_manager

            return list(get_identity_binding_manager().identity_set_for("l3a", _p.L3AC_PEER_ROLE))
        except Exception as e:
            logger.debug("l3a secretary: identity tags skipped: %s", e)
            capture(
                "l3a secretary: identity tags skipped", error_code="E_L3AC", component="l3a", context={"error": str(e)}
            )
            return []

    def _persist_contribution(self, kind: str, success: bool, card_id: str) -> str:
        """Write the contribution into the secretary's memory scope + R5.

        Uses the generic scope accessor (get_memory(scope)) so the record
        lands in the secretary's own R1-R3 ring ("l3a" default or an
        evolved "l3a-c-<n>"); the R5 graph gets an evidence edge when the
        graph is enabled. All failures degrade gracefully (returns "").
        """
        try:
            from l3.memory.central_memory import get_memory

            mem = get_memory(self._scope)
            content = (
                f"l3a secretary contribution: kind={kind} success={success}"
                f" card={card_id or 'none'} scope={self._scope} at={int(time.time())}"
            )
            entry_id = mem.remember(
                agent_id=_p.AGENT_ID,
                entry_type="l3a_secretary_contribution",
                content=content,
                tags=["l3a", "secretary", kind] + self._identity_tags(),
                source="l3a_secretary",
                importance=0.8 if success else 0.4,
                ring=1,
                cell_id="l3a",
            )
            # R5 graph edge (evidence relation) — non-blocking when off.
            try:
                from l3.memory.memory_graph import get_graph

                g = get_graph()
                if g.enabled and entry_id and not str(entry_id).startswith("REJECTED"):
                    g.add_evidence_edge(
                        entry_id,
                        card_id or entry_id,
                        weight=1.0 if success else 0.5,
                        created_by="l3a_secretary",
                    )
            except Exception as e:
                logger.debug("l3a secretary: R5 edge skipped: %s", e)
            return entry_id if not str(entry_id).startswith("REJECTED") else ""
        except Exception as e:
            logger.debug("l3a secretary: contribution persist skipped: %s", e)
            capture(
                "l3a secretary: contribution persist skipped",
                error_code="E_L3AC",
                component="l3a",
                context={"error": str(e)},
            )
            return ""

    def scope(self) -> str:
        """Return the secretary's memory scope ("l3a" or "l3a-c-<n>")."""
        with self._lock:
            return self._scope

    def set_scope(self, scope: str) -> dict:
        """Bind the secretary to a memory scope (extension-first, no hardcode)."""
        with self._lock:
            self._scope = scope or "l3a"
        return {"success": True, "scope": self._scope}

    def peer_session_id(self) -> str:
        """Return the background session id spawned on upgrade ("" before)."""
        with self._lock:
            return self._peer_session_id

    def _spawn_peer_session(self) -> str:
        """Create the secretary's own background session (peer entity).

        The session is bound to the secretary's memory scope and identity
        (role ``l3a-secretary``) so its R1-R3 memory + identity fragment
        follow it. Idempotent; returns the session id.
        """
        with self._lock:
            if self._peer_session_id:
                return self._peer_session_id
        try:
            # Create via the L3A daemon's authoritative session manager so
            # the peer session is registered where L3A can dispatch to it.
            from l3.cell.peers.l3a import get_daemon

            manager = get_daemon().manager
            s = manager.create(
                title="l3a-secretary-peer",
                memory_scope=self._scope,
                cell_id="l3a",
                role=_p.L3AC_PEER_ROLE,
            )
            with self._lock:
                self._peer_session_id = s.id
            return s.id
        except Exception as e:
            logger.debug("l3a secretary: peer session spawn failed: %s", e)
            capture(
                "l3a secretary: peer session spawn failed",
                error_code="E_L3AC",
                component="l3a",
                context={"error": str(e)},
            )
            return ""

    def enabled(self) -> bool:
        """Return whether the secretary is active (settings switch, default on).

        An in-memory override set via ``set_enabled`` (API) wins over the
        settings default — the toggle is operator-controllable, not
        hardcoded.
        """
        with self._lock:
            if self._enabled_override is not None:
                return self._enabled_override
        try:
            from l1.kernel.settings import get_settings

            return bool(get_settings().get("l3a.secretary.enabled", _p.L3AC_ENABLED_DEFAULT))
        except Exception as e:
            logger.warning("l3a secretary: settings lookup failed, defaulting to on: %s", e)
            return _p.L3AC_ENABLED_DEFAULT

    def set_enabled(self, enabled: bool) -> dict:
        """Override the secretary's active switch at runtime (API/configured).

        ``None`` clears the override and returns to the settings default.
        """
        with self._lock:
            self._enabled_override = None if enabled is None else bool(enabled)
        logger.info("l3a secretary: enabled override -> %s", self._enabled_override)
        return {"success": True, "enabled": self.enabled()}

    def set_threshold(self, threshold: int) -> dict:
        """Adjust the assist→peer capability threshold at runtime (API).

        Threshold must be >= 0; a threshold of 0 restores the params
        default. Never hardcoded — operator-tunable via the API surface.
        """
        if threshold < 0:
            return {"success": False, "error": "threshold must be >= 0"}
        with self._lock:
            self._threshold = threshold or _p.L3AC_CAPABILITY_THRESHOLD
        logger.info("l3a secretary: threshold -> %d", self._threshold)
        return {"success": True, "threshold": self._threshold}

    def set_mode(self, mode: str) -> dict:
        """Force the mode explicitly (assist|peer|auto) instead of the
        score-based automatic transition.

        ``auto`` (default) keeps the score-driven upgrade; ``assist`` /
        ``peer`` pin the mode until changed — the transition is no longer
        code-embedded only, it is operator-controllable.
        """
        if mode not in ("auto", _p.L3AC_MODE_ASSIST, _p.L3AC_MODE_PEER):
            return {"success": False, "error": f"invalid mode: {mode!r} (auto|assist|peer)"}
        with self._lock:
            self._mode_override = None if mode == "auto" else mode
        return {"success": True, "mode": self.mode()}

    def score(self) -> int:
        """Return the current capability score."""
        with self._lock:
            return self._score

    def mode(self) -> str:
        """Return "peer" when the capability threshold is reached, else "assist".

        An explicit operator override (set_mode) pins the mode; otherwise
        the score-driven transition applies.
        """
        with self._lock:
            if self._mode_override:
                return self._mode_override
        return _p.L3AC_MODE_PEER if self.score() >= self._threshold else _p.L3AC_MODE_ASSIST

    def commission_spec(self) -> str:
        """Return the subagent spec for the current mode (assist vs peer)."""
        return _p.L3AC_SPEC_PEER if self.mode() == _p.L3AC_MODE_PEER else _p.L3AC_SPEC_ASSIST

    def status(self) -> dict:
        """Return secretary status (score, mode, spec, contribution count)."""
        with self._lock:
            return {
                "score": self._score,
                "threshold": self._threshold,
                "mode": self.mode(),
                "spec": self.commission_spec(),
                "contributions": len(self._contributions),
            }


_secretary: L3ACSecretary | None = None
_secretary_lock = threading.Lock()
_secretaries: dict[str, L3ACSecretary] = {}  # D3: scope -> secretary instance
_secretaries_lock = threading.Lock()


def get_secretary() -> L3ACSecretary:
    """Get the global L3A-C secretary singleton (double-checked locking)."""
    global _secretary
    if _secretary is None:
        with _secretary_lock:
            if _secretary is None:
                _secretary = L3ACSecretary()
    return _secretary


def get_or_create_secretary(scope: str = "l3a") -> L3ACSecretary:
    """Get (or lazily create) a secretary instance for a memory scope (D3).

    Decision-body evolution: each evolved secretary owns an isolated
    ``l3a-c-<n>`` scope (extension-first — any scope is a secretary). The
    default ``l3a`` scope maps to the canonical singleton so existing
    callers keep working.

    Args:
        scope: Memory scope of the secretary (default "l3a").

    Returns:
        The L3ACSecretary instance bound to that scope.
    """
    scope = scope or "l3a"
    if scope == "l3a":
        return get_secretary()
    with _secretaries_lock:
        sec = _secretaries.get(scope)
        if sec is None:
            sec = L3ACSecretary()
            sec.set_scope(scope)
            _secretaries[scope] = sec
        return sec


def list_secretaries() -> list[dict]:
    """List all evolved secretary instances (scope + mode + score)."""
    with _secretaries_lock:
        return [{"scope": s, "mode": sec.mode(), "score": sec.score()} for s, sec in sorted(_secretaries.items())]


def reset_secretary() -> None:
    """Reset the singleton and the evolved-secretary registry (used by tests)."""
    global _secretary
    with _secretary_lock:
        _secretary = None
    with _secretaries_lock:
        _secretaries.clear()
