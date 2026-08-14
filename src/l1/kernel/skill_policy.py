"""SkillPolicyMixin — runtime policy knobs for SkillManager.

Extracted from skill.py.  The mixin holds every ``set_*_policy`` /
``*_policy`` pair plus the offensive-posture gate; the concrete
``SkillManager`` composes it with the guidance/persist/retrieval mixins
and owns the shared state (``self._lock``, ``self._*_policy`` fields).
"""

from __future__ import annotations

import logging
import threading
import time

from l1.kernel.params.system import SKILL_GUIDANCE_MODES

logger = logging.getLogger(__name__)


class SkillPolicyMixin:
    """SkillPolicyMixin — distill/pipeline/disclosure/guidance/write/offensive policy knobs."""

    # ── Attributes injected by the concrete SkillManager (see skill.py) ──
    _lock: threading.RLock
    _distill_enabled: bool
    _dpo_signal_enabled: bool
    _distill_sub: dict[str, bool]
    _distill_updated: float
    _distill_source: str
    _retrieval_enabled: bool
    _curation_enabled: bool
    _contrib_min_trials: int
    _contrib_min_ratio: float
    _retrieval_min_score: float
    _pipeline_updated: float
    _pipeline_source: str
    _full_index_enabled: bool
    _full_index_limit: int
    _audience_filter_enabled: bool
    _strategy_capability_view: bool
    _disclosure_updated: float
    _disclosure_source: str
    _guidance_mode: str
    _guidance_updated: float
    _guidance_source: str
    _write_min_ring: int
    _write_roles: tuple[str, ...]
    _offensive_enabled: bool
    _offensive_natures: tuple[str, ...]

    def set_distill_policy(
        self,
        distill: bool | None = None,
        dpo_signal: bool | None = None,
        sub: dict | None = None,
        source: str = "runtime",
    ) -> dict:
        """Override the distillation/DPO switches at runtime (API/config).

        ``distill=False`` disables the whole pipeline (master);
        ``dpo_signal=False`` disables card→skill preference weighting;
        ``sub`` optionally sets individual stage switches, e.g.
        ``{"clustering": False}`` degrades clustering only (falls back to
        by-tool grouping). ``source`` records who last changed the policy
        (params/config/runtime/API) for auditability. None fields are left
        untouched, so a caller can flip just one knob.
        """
        with self._lock:
            if distill is not None:
                self._distill_enabled = bool(distill)
            if dpo_signal is not None:
                self._dpo_signal_enabled = bool(dpo_signal)
            if sub and isinstance(sub, dict):
                for k, v in sub.items():
                    if k in self._distill_sub:
                        self._distill_sub[k] = bool(v)
            if distill is not None or dpo_signal is not None or sub:
                self._distill_updated = time.time()
                self._distill_source = source
            return {
                "success": True,
                "distill": self._distill_enabled,
                "dpo_signal": self._dpo_signal_enabled,
                "sub": dict(self._distill_sub),
                "updated": self._distill_updated,
                "source": self._distill_source,
            }

    def distill_policy(self) -> dict:
        """Return the current distillation/DPO policy (master + sub-switches)."""
        with self._lock:
            return {
                "distill": self._distill_enabled,
                "dpo_signal": self._dpo_signal_enabled,
                "sub": dict(self._distill_sub),
                "updated": self._distill_updated,
                "source": self._distill_source,
            }

    def set_pipeline_policy(
        self,
        retrieval: bool | None = None,
        curation: bool | None = None,
        contrib_min_trials: int | None = None,
        contrib_min_ratio: float | None = None,
        retrieval_min_score: float | None = None,
        source: str = "runtime",
    ) -> dict:
        """Override the retrieval/curation pipeline knobs at runtime (API/config).

        ``retrieval=False`` disables task-similarity ranking (falls back to
        deterministic ordering); ``curation=False`` disables contribution-based
        retirement/eviction; the threshold fields tune scoring granularity.
        None fields are left untouched. ``source`` records who changed the
        policy for auditability.
        """
        with self._lock:
            if retrieval is not None:
                self._retrieval_enabled = bool(retrieval)
            if curation is not None:
                self._curation_enabled = bool(curation)
            if contrib_min_trials is not None:
                self._contrib_min_trials = int(contrib_min_trials)
            if contrib_min_ratio is not None:
                self._contrib_min_ratio = float(contrib_min_ratio)
            if retrieval_min_score is not None:
                self._retrieval_min_score = float(retrieval_min_score)
            self._pipeline_updated = time.time()
            self._pipeline_source = source
            return {
                "success": True,
                "retrieval": self._retrieval_enabled,
                "curation": self._curation_enabled,
                "contrib_min_trials": self._contrib_min_trials,
                "contrib_min_ratio": self._contrib_min_ratio,
                "retrieval_min_score": self._retrieval_min_score,
                "updated": self._pipeline_updated,
                "source": self._pipeline_source,
            }

    def pipeline_policy(self) -> dict:
        """Return the current retrieval/curation pipeline policy."""
        with self._lock:
            return {
                "retrieval": self._retrieval_enabled,
                "curation": self._curation_enabled,
                "contrib_min_trials": self._contrib_min_trials,
                "contrib_min_ratio": self._contrib_min_ratio,
                "retrieval_min_score": self._retrieval_min_score,
                "updated": self._pipeline_updated,
                "source": self._pipeline_source,
            }

    def set_disclosure_policy(
        self,
        full_index_enabled: bool | None = None,
        full_index_limit: int | None = None,
        audience_filter_enabled: bool | None = None,
        strategy_capability_view: bool | None = None,
        source: str = "runtime",
    ) -> dict:
        """Override the progressive-disclosure knobs at runtime (API/config).

        ``full_index_enabled`` appends the full skill index after the curated
        catalog slots; ``audience_filter_enabled`` toggles strategy/execution
        audience routing; ``strategy_capability_view`` gives the L3A decision
        layer a read-only view of execution capabilities. None fields are
        left untouched; ``source`` records who changed the policy.
        """
        with self._lock:
            if full_index_enabled is not None:
                self._full_index_enabled = bool(full_index_enabled)
            if full_index_limit is not None:
                self._full_index_limit = int(full_index_limit)
            if audience_filter_enabled is not None:
                self._audience_filter_enabled = bool(audience_filter_enabled)
            if strategy_capability_view is not None:
                self._strategy_capability_view = bool(strategy_capability_view)
            self._disclosure_updated = time.time()
            self._disclosure_source = source
            return {
                "success": True,
                "full_index_enabled": self._full_index_enabled,
                "full_index_limit": self._full_index_limit,
                "audience_filter_enabled": self._audience_filter_enabled,
                "strategy_capability_view": self._strategy_capability_view,
                "updated": self._disclosure_updated,
                "source": self._disclosure_source,
            }

    def disclosure_policy(self) -> dict:
        """Return the current progressive-disclosure policy."""
        with self._lock:
            return {
                "full_index_enabled": self._full_index_enabled,
                "full_index_limit": self._full_index_limit,
                "audience_filter_enabled": self._audience_filter_enabled,
                "strategy_capability_view": self._strategy_capability_view,
                "updated": self._disclosure_updated,
                "source": self._disclosure_source,
            }

    def set_guidance_policy(self, mode: str | None = None, source: str = "runtime") -> dict:
        """Override the guidance operating mode (small|full) at runtime.

        ``small`` treats the guidance fields (stages/next/dependencies) as
        inert — skills execute as plain skills; ``full`` activates the atomic
        stage-granularity chains (frontier unlock, stage disclosure, TODO
        linkage). A None mode leaves the current mode untouched.
        """
        with self._lock:
            if mode is not None:
                if mode not in SKILL_GUIDANCE_MODES:
                    return {
                        "success": False,
                        "error": f"invalid guidance mode '{mode}' (expected {SKILL_GUIDANCE_MODES})",
                    }
                self._guidance_mode = mode
            self._guidance_updated = time.time()
            self._guidance_source = source
            return self.guidance_policy()

    def guidance_policy(self) -> dict:
        """Return the current guidance operating mode (small|full)."""
        with self._lock:
            return {
                "mode": self._guidance_mode,
                "updated": self._guidance_updated,
                "source": self._guidance_source,
            }

    def set_write_policy(self, min_ring: int | None = None, roles: list[str] | tuple[str, ...] | None = None) -> dict:
        """Override the write-gate policy (called by L3 config center / API).

        Args:
            min_ring: Minimum ring clearance to mutate skills.
            roles: Additional roles allowed to mutate skills.
        """
        with self._lock:
            if min_ring is not None:
                self._write_min_ring = int(min_ring)
            if roles is not None:
                self._write_roles = tuple(roles)
        return {
            "success": True,
            "write_min_ring": self._write_min_ring,
            "write_roles": list(self._write_roles),
        }

    def write_policy(self) -> dict:
        """Return the current write-gate policy (for API/CLI exposure)."""
        with self._lock:
            return {
                "write_min_ring": self._write_min_ring,
                "write_roles": list(self._write_roles),
            }

    def set_offensive_policy(
        self,
        enabled: bool | None = None,
        natures: list[str] | tuple[str, ...] | None = None,
    ) -> dict:
        """Override the offensive-posture gate policy at runtime (API/config).

        Soft control ("honest-agent" gate): ``enabled=False`` bypasses the
        posture gate entirely; ``natures`` replaces the card natures that
        authorize offensive-skill injection. Neither field is required, so a
        caller can flip just one. Applied atomically under the manager lock.
        """
        with self._lock:
            if enabled is not None:
                self._offensive_enabled = bool(enabled)
            if natures is not None:
                self._offensive_natures = tuple(n for n in natures if isinstance(n, str))
            result = {
                "success": True,
                "enabled": self._offensive_enabled,
                "natures": list(self._offensive_natures),
            }
        # Best-effort bus event: soft-bypass switches are observable evidence
        # (L3 evidence chain subscribes; a failing emit never breaks the set).
        try:
            from l1.kernel.event import get_bus

            get_bus().emit_event(
                "security_policy_change",
                data={"enabled": result["enabled"], "natures": result["natures"]},
                source="policy",
            )
        except Exception:
            pass
        return result

    def offensive_policy(self) -> dict:
        """Return the current offensive-posture gate policy (for API/CLI)."""
        with self._lock:
            return {
                "enabled": self._offensive_enabled,
                "natures": list(self._offensive_natures),
            }

    def offensive_authorized(self, nature: str) -> bool:
        """Whether an offensive-posture skill may be used for a card nature.

        Gate disabled → authorized for any nature (soft-control bypass).
        Gate enabled → authorized only for natures in the policy allow-list
        (default: SKILL_OFFENSIVE_AUTHORIZED_NATURES). Consulted by AgentLoop
        injection, SkillCatalogHook and use_skill.
        """
        with self._lock:
            if not self._offensive_enabled:
                return True
            return nature in self._offensive_natures
