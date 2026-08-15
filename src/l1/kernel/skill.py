"""Skill system — loadable agent capabilities.

Skills are YAML/Markdown files that define:
  - Knowledge: architecture, conventions, domain expertise
  - Rules: coding standards, review criteria, testing requirements
  - Procedures: step-by-step workflows

Skills are mounted in VFS at /skills/ and agents can query them.

Implementation note: ``SkillManager`` is composed from four same-layer
mixin modules (extracted from this file):

  - skill_policy.py     → policy knobs (distill/pipeline/disclosure/
                           guidance/write/offensive)
  - skill_guidance.py   → quest-style staged skills + guidance DAG
  - skill_persist.py    → discovery-dir loading, SKILL.md/YAML parse,
                           frontmatter normalization, registry store
  - skill_retrieval.py  → query / catalog listing / structured view

Usage:
  from l1.kernel.skill import get_skill_manager
  sm = get_skill_manager()
  sm.load("python_style")
  sm.get("python_style")  # → {"name": "...", "rules": [...]}
  sm.list_skills()               # → all loaded skills
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Final

from l1.kernel.params.agent import (
    AGENT_CLEARANCE,
    R4_CONTRIB_MIN_RATIO,
    R4_CONTRIB_MIN_TRIALS,
    R4_CURATION_ENABLED,
    R4_DISTILL_ENABLED,
    R4_DISTILL_SUB_CLUSTERING,
    R4_DISTILL_SUB_GENERALIZE,
    R4_DISTILL_SUB_LLM,
    R4_DISTILL_SUB_SAMPLING,
    R4_DPO_SIGNAL_ENABLED,
    R4_RETRIEVAL_ENABLED,
    R4_RETRIEVAL_MIN_SCORE,
)
from l1.kernel.params.system import (
    LOG_TRUNC_200,
    LOG_TRUNC_2000,
    SKILL_AUDIENCE_FILTER_ENABLED,
    SKILL_CATALOG_FULL_INDEX_ENABLED,
    SKILL_CATALOG_FULL_INDEX_LIMIT,
    SKILL_CONTRACT_FORBIDDEN_PATHS,
    SKILL_CONTRACT_FORBIDDEN_PATTERNS,
    SKILL_DISCLOSURE_DEFAULT,
    SKILL_GUIDANCE_MODE_DEFAULT,
    SKILL_OFFENSIVE_AUTHORIZED_NATURES,
    SKILL_OFFENSIVE_ENABLED,
    SKILL_POSTURE_DEFAULT,
    SKILL_STATUS_DEFAULT,
    SKILL_STATUS_VALID,
    SKILL_STRATEGY_CAPABILITY_VIEW,
    SKILL_WRITE_MIN_RING,
    SKILL_WRITE_ROLES,
)

from .skill_guidance import SkillGuidanceMixin
from .skill_persist import SkillPersistMixin
from .skill_policy import SkillPolicyMixin
from .skill_retrieval import SkillRetrievalMixin

logger = logging.getLogger(__name__)


def validate_skill_content(prompt: str, description: str = "") -> list[str]:
    """Validate evolved-skill content against the built-in catalog contract.

    Checks a skill's prompt+description for:
      1. Constitutional-violation instructions (bypass sandbox, modify
         constitution, write outside territory, skip gates, swallow
         exceptions) — mirror of ``test_skill_contracts`` patterns.
      2. Project-specific path/identifier literals that would prevent the
         skill from generalizing to other projects.

    Returns the list of violations (empty = clean). The caller decides
    whether to scrub or reject; this function never mutates anything.
    """
    import re as _re

    violations: list[str] = []
    text = f"{prompt or ''}\n{description or ''}"
    for pat in SKILL_CONTRACT_FORBIDDEN_PATTERNS:
        if _re.search(pat, text, _re.IGNORECASE):
            violations.append(f"constitutional pattern: {pat}")
    for lit in SKILL_CONTRACT_FORBIDDEN_PATHS:
        if lit in text:
            violations.append(f"project-specific literal: {lit}")
    return violations


def _derive_role(agent_id: str) -> str:
    """Derive a role name from an agent id (``agent-writer`` → ``writer``)."""
    if agent_id in ("l3", "human"):
        return agent_id
    for prefix in ("agent-", "agent_"):
        if agent_id.startswith(prefix):
            return agent_id[len(prefix) :]
    return agent_id


@dataclass
class Skill:
    """Skill — skill record (name, description, rules, procedures, knowledge)."""

    name: str
    description: str = ""
    rules: list[str] = field(default_factory=list)
    procedures: list[dict] = field(default_factory=list)
    knowledge: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    loaded_at: float = 0.0
    allowed_tools: list[str] | None = None
    variables: list[str] | None = None
    prompt: str = ""
    posture: str = SKILL_POSTURE_DEFAULT

    def expand(self, **kwargs: str) -> str:
        """Expand $VARIABLES in prompt with keyword args."""
        if not self.prompt:
            return self.prompt
        result = self.prompt
        for k, v in kwargs.items():
            result = result.replace(f"${k.upper()}", str(v))
        return result

    def to_dict(self) -> dict:
        """Serialize the skill to a plain dict for inspection and persistence."""
        return {
            "name": self.name,
            "description": self.description,
            "rules": len(self.rules),
            "procedures": len(self.procedures),
            "knowledge": self.knowledge,
            "source": self.source,
            "allowed_tools": self.allowed_tools or [],
            "variables": self.variables or [],
            "prompt": self.prompt or "",
            "tags": [],
            "posture": self.posture,
            "loaded_at": self.loaded_at,
        }


class SkillManager(SkillPolicyMixin, SkillGuidanceMixin, SkillPersistMixin, SkillRetrievalMixin):
    """Manages agent skills — load, list, query at runtime."""

    def __init__(self):
        self._skills: dict[str, dict] = {}
        # RLock: delete() calls _drop_skill_from_cells() while holding the lock
        # (reentrant — see AGENTS.md threading convention).
        self._lock = threading.RLock()
        # Per-Cell skill white-list: cell_id → set of skill names.
        # Cells bind the skills they are allowed to inject; unbound cells
        # fall back to the global pool (backward compatible).
        self._cell_skill_map: dict[str, set[str]] = {}
        # Write-gate policy — compile-time defaults; L3 config center may
        # inject overrides via set_write_policy() (kernel never imports L3).
        self._write_min_ring: int = SKILL_WRITE_MIN_RING
        self._write_roles: tuple[str, ...] = SKILL_WRITE_ROLES
        # Offensive-posture gate policy — compile-time defaults; L3 config
        # center and the API may inject overrides via set_offensive_policy()
        # at runtime (soft control, see SKILL_OFFENSIVE_ENABLED).
        self._offensive_enabled: bool = SKILL_OFFENSIVE_ENABLED
        self._offensive_natures: tuple[str, ...] = SKILL_OFFENSIVE_AUTHORIZED_NATURES
        # Distillation/DPO master switches — compile-time defaults; the API
        # and config center may override at runtime (see
        # /api/v2/skills/distill-policy). R4Agent gates its pipeline on these.
        # ``_distill_sub`` holds the per-stage sub-switches (generalize /
        # llm_distill / clustering / sampling) so the pipeline can degrade
        # one notch at a time instead of all-or-nothing.
        self._distill_enabled: bool = R4_DISTILL_ENABLED
        self._dpo_signal_enabled: bool = R4_DPO_SIGNAL_ENABLED
        self._distill_sub: dict[str, bool] = {
            "generalize": R4_DISTILL_SUB_GENERALIZE,
            "llm_distill": R4_DISTILL_SUB_LLM,
            "clustering": R4_DISTILL_SUB_CLUSTERING,
            "sampling": R4_DISTILL_SUB_SAMPLING,
        }
        self._distill_updated: float = 0.0
        self._distill_source: str = "params"
        # Retrieval/curation pipeline policy — runtime knobs for the R4
        # pipeline stages (task-similarity ranking, contribution curation and
        # their scoring thresholds). Overridable via set_pipeline_policy();
        # params provide the compile-time defaults.
        self._retrieval_enabled: bool = R4_RETRIEVAL_ENABLED
        self._curation_enabled: bool = R4_CURATION_ENABLED
        self._contrib_min_trials: int = R4_CONTRIB_MIN_TRIALS
        self._contrib_min_ratio: float = R4_CONTRIB_MIN_RATIO
        self._retrieval_min_score: float = R4_RETRIEVAL_MIN_SCORE
        self._pipeline_updated: float = 0.0
        self._pipeline_source: str = "params"
        # Progressive-disclosure policy — runtime knobs for the session
        # catalog (two-level index, audience filter, L3A capability view).
        self._full_index_enabled: bool = SKILL_CATALOG_FULL_INDEX_ENABLED
        self._full_index_limit: int = SKILL_CATALOG_FULL_INDEX_LIMIT
        self._audience_filter_enabled: bool = SKILL_AUDIENCE_FILTER_ENABLED
        self._strategy_capability_view: bool = SKILL_STRATEGY_CAPABILITY_VIEW
        self._disclosure_updated: float = 0.0
        self._disclosure_source: str = "params"
        # Guidance operating mode: small (fields inert, plain skills) or full
        # (atomic stage-granularity chains active).
        self._guidance_mode: str = SKILL_GUIDANCE_MODE_DEFAULT
        self._guidance_updated: float = 0.0
        self._guidance_source: str = "params"
        # Quest-style staged skills: (skill, session_key) → active stage index.
        self._stage_state: dict[tuple[str, str], int] = {}
        self._stage_touched: dict[tuple[str, str], float] = {}
        self._last_stage_prune: float = 0.0
        # Universal principles normalized into a single shared layer
        # (config/skills/_shared/principles.md) — injected at load time.
        self._shared_principles: str = ""
        # Structural-mutation revision — R4Agent injection caches compare this
        # to decide whether their derived skill lists are stale.
        self._revision = 0

    # ── Per-Cell skill binding (inject back into Cell) ──

    def bind_skill(self, cell_id: str, name: str) -> dict:
        """Bind a skill to a Cell so it is injected only for that Cell.

        Args:
            cell_id: Cell identifier.
            name: Skill name to allow for the Cell.
        """
        with self._lock:
            if name not in self._skills:
                return {"success": False, "error": f"skill '{name}' not found"}
            self._cell_skill_map.setdefault(cell_id, set()).add(name)
            self._revision += 1
            return {"success": True, "cell_id": cell_id, "skill": name}

    def unbind_skill(self, cell_id: str, name: str) -> dict:
        """Remove a skill binding from a Cell."""
        with self._lock:
            cell_set = self._cell_skill_map.get(cell_id)
            if not cell_set or name not in cell_set:
                return {"success": False, "error": f"skill '{name}' not bound to '{cell_id}'"}
            cell_set.discard(name)
            self._revision += 1
            return {"success": True, "cell_id": cell_id, "skill": name}

    def skills_for_cell(self, cell_id: str) -> set[str]:
        """Return the set of skill names bound to a Cell (empty = global pool)."""
        with self._lock:
            return set(self._cell_skill_map.get(cell_id, set()))

    def cells_for_skill(self, name: str) -> list[str]:
        """Return all Cell ids that have bound this skill."""
        with self._lock:
            return [cid for cid, s in self._cell_skill_map.items() if name in s]

    def _drop_skill_from_cells(self, name: str) -> None:
        """Remove a deleted skill from every Cell binding."""
        with self._lock:
            for cell_set in self._cell_skill_map.values():
                cell_set.discard(name)

    @staticmethod
    def _normalize_binding(binding: dict | None) -> dict[str, list[str]]:
        """Normalize the optional injection binding stored on a skill."""
        source = binding if isinstance(binding, dict) else {}
        normalized: dict[str, list[str]] = {}
        for key in ("cell_ids", "roles", "agent_ids", "card_natures", "postures"):
            value = source.get(key, [])
            if isinstance(value, str):
                value = [value]
            normalized[key] = sorted({item.strip() for item in value if isinstance(item, str) and item.strip()})
        return normalized

    def skill_is_injectable(
        self,
        skill: dict,
        agent_id: str = "",
        cell_id: str = "",
        role: str = "",
        card_tags: list[str] | None = None,
        posture: str = SKILL_POSTURE_DEFAULT,
    ) -> bool:
        """Return whether a skill lifecycle state and binding allow injection."""
        status = str(skill.get("status", SKILL_STATUS_DEFAULT) or SKILL_STATUS_DEFAULT)
        if status not in SKILL_STATUS_VALID or status in ("draft", "retired", "deprecated"):
            return False
        binding = self._normalize_binding(skill.get("binding"))
        explicit_targets = any(binding[key] for key in ("cell_ids", "roles", "agent_ids", "card_natures"))
        resolved_role = role or _derive_role(agent_id)
        card_natures = {
            tag[len("card:") :] if tag.startswith("card:") else tag
            for tag in (card_tags or [])
            if isinstance(tag, str) and tag
        }
        constraints = (
            status != "canary" or explicit_targets,
            not binding["cell_ids"] or cell_id in binding["cell_ids"],
            not binding["roles"] or resolved_role in binding["roles"],
            not binding["agent_ids"] or agent_id in binding["agent_ids"],
            not binding["card_natures"] or bool(card_natures.intersection(binding["card_natures"])),
            not binding["postures"] or posture in binding["postures"],
        )
        return all(constraints)

    def authorize_write(self, agent_id: str = "", role: str = "", internal: bool = False) -> tuple[bool, str]:
        """Check whether a caller may create/update/delete skills.

        Developer-only policy: only roles with ring clearance >=
        ``skill.write_min_ring`` (SettingsCenter-configurable, default
        ``SKILL_WRITE_MIN_RING``) or in ``skill.write_roles`` (default
        ``SKILL_WRITE_ROLES``) may mutate skills; ordinary users are
        read-only.  A caller with neither ``agent_id`` nor ``role`` is
        treated as a system-internal caller and allowed **only** when
        ``internal=True`` (boot-time loading, R4Agent evolution/pruning).
        External entry points (shell/API) must pass an explicit identity
        and may not claim ``system`` by omission.
        """
        if not agent_id and not role:
            return (True, "system") if internal else (False, "identity required: provide agent_id or role")
        with self._lock:
            min_ring = self._write_min_ring
            write_roles = self._write_roles
        resolved = role or _derive_role(agent_id)
        ring = AGENT_CLEARANCE.get(resolved, 0)
        if resolved in write_roles or ring >= min_ring:
            return True, resolved
        return False, (
            f"role '{resolved}' (ring {ring}) lacks skill write clearance "
            f"(need ring>={min_ring} or role in {list(write_roles)})"
        )

    def register(self, name: str, data: dict, agent_id: str = "", role: str = "", internal: bool = False) -> dict:
        """Register a skill programmatically (developer-only).

        ``internal=True`` allows identity-less writes from system processes
        (boot loading, R4Agent); external callers must pass an identity.
        """
        ok, who = self.authorize_write(agent_id, role, internal=internal)
        if not ok:
            return {"success": False, "error": f"permission denied: {who}"}
        with self._lock:
            existing = self._skills.get(name)
        if existing and existing.get("builtin"):
            return {"success": False, "error": f"permission denied: builtin skill '{name}' is read-only"}
        with self._lock:
            self._skills[name] = data
            self._revision += 1
            self._emit_mutated("register", name, agent_id, who)
            return {"success": True, "skill": name, "authorized": who}

    def create(
        self,
        name: str,
        description: str = "",
        prompt: str = "",
        tags: list[str] | None = None,
        rules: list[str] | None = None,
        procedures: list[dict] | None = None,
        allowed_tools: list[str] | None = None,
        dependencies: list[str] | None = None,
        dependency_kind: str = "soft",
        posture: str = SKILL_POSTURE_DEFAULT,
        disclosure: str = SKILL_DISCLOSURE_DEFAULT,
        stages: list[dict] | None = None,
        next_skills: list[str] | None = None,
        knowledge: dict | None = None,
        layer: str = "",
        binding: dict | None = None,
        status: str = "",
        agent_id: str = "",
        role: str = "",
        internal: bool = False,
    ) -> dict:
        """Create a skill programmatically with structured fields (developer-only).

        ``internal=True`` allows identity-less writes from system processes
        (boot loading, R4Agent); external callers must pass an identity.
        ``layer`` tags the generalization layer (``"exec"`` execution-layer
        tool skills / ``"decision"`` decision-layer reasoning skills; "" =
        unlayered), indexed by ``list_skills(layer=...)`` (P0-②).
        """
        ok, who = self.authorize_write(agent_id, role, internal=internal)
        if not ok:
            return {"success": False, "error": f"permission denied: {who}"}
        data = {
            "name": name,
            "description": description[:LOG_TRUNC_200],
            "prompt": prompt,
            "rules": rules or [],
            "procedures": procedures or [],
            "knowledge": knowledge if knowledge is not None else {"evolved": True, "prompt": prompt[:LOG_TRUNC_2000]},
            "tags": tags or [],
            "allowed_tools": allowed_tools,
            "dependencies": dependencies or [],
            "dependency_kind": dependency_kind if dependency_kind in ("hard", "soft") else "soft",
            "posture": self._normalize_posture(posture),
            "disclosure": self._normalize_disclosure(disclosure),
            "stages": [s for s in (stages or []) if isinstance(s, dict)],
            "next": [n for n in (next_skills or []) if isinstance(n, str)],
            "source": "evolved",
            "loaded_at": __import__("time").time(),
            "useful_count": 0,
            "layer": layer if layer in ("exec", "decision") else "",
            "binding": self._normalize_binding(binding),
            "status": status if status in SKILL_STATUS_VALID else "",
        }
        return self.register(name, data, agent_id=agent_id, role=role, internal=internal)

    def update(self, name: str, data: dict, agent_id: str = "", role: str = "", internal: bool = False) -> dict:
        """Update a skill's data at runtime (developer-only).

        Ordinary callers may only bump usage metadata (``last_used``);
        structural edits require write clearance.  ``internal=True`` allows
        identity-less structural writes from system processes.
        """
        ok, who = self.authorize_write(agent_id, role, internal=internal)
        with self._lock:
            if name not in self._skills:
                return {"success": False, "error": f"skill '{name}' not found"}
            builtin = bool(self._skills[name].get("builtin"))
            # Usage bookkeeping is harmless for any caller.
            if set(data.keys()) <= {"last_used", "usage_count", "useful_count"}:
                self._skills[name].update(data)
                return {"success": True, "skill": name}
            if builtin:
                return {"success": False, "error": f"permission denied: builtin skill '{name}' is read-only"}
            if not ok:
                return {"success": False, "error": f"permission denied: {who}"}
            self._skills[name].update(data)
            self._revision += 1
            self._emit_mutated("update", name, agent_id, who)
            return {"success": True, "skill": name, "authorized": who}

    def bump_usage(self, name: str, key: str = "useful_count") -> dict:
        """Atomically increment a usage counter on a skill.

        Performs the read-modify-write under a single lock acquisition so
        concurrent callers (e.g. parallel ``use_skill`` invocations) never
        lose an increment.  Usage bookkeeping requires no write clearance.
        """
        with self._lock:
            if name not in self._skills:
                return {"success": False, "error": f"skill '{name}' not found"}
            current = self._skills[name].get(key, 0) or 0
            self._skills[name][key] = current + 1
            self._skills[name]["last_used"] = time.time()
        self._emit_usage_feedback(name)
        return {"success": True, "skill": name, key: current + 1}

    def _emit_usage_feedback(self, name: str) -> None:
        """Notify the registered skill→memory feedback hooks (P1-③).

        The feedback hooks (installed by the L3 skill-memory feedback
        module) batch skill-usage events into R3 memory writes
        (entry_type=skill_usage). Bypass: a failing hook never affects the
        usage bump itself.
        """
        for fn in list(_USAGE_FEEDBACK_HOOKS):
            with suppress(Exception):  # bypass: never affect the usage bump
                fn(name)

    def bump_usage_for_tools(self, tool_names: list[str], key: str = "useful_count") -> dict:
        """Atomically bump usage for every skill whose name matches a tool.

        The three-table linkage (TODO × card × skill) drives this: when a
        tool succeeds (or a task/card completes), skills named after the
        tool gain a usage point. All bumps happen under one lock acquisition
        so parallel callers never lose increments. Unknown names are
        reported, not raised — linkage must degrade gracefully.
        """
        bumped: list[str] = []
        missing: list[str] = []
        with self._lock:
            for name in tool_names:
                if name not in self._skills:
                    missing.append(name)
                    continue
                current = self._skills[name].get(key, 0) or 0
                self._skills[name][key] = current + 1
                self._skills[name]["last_used"] = time.time()
                bumped.append(name)
        return {"success": True, "bumped": bumped, "missing": missing}

    def revision(self) -> int:
        """Return the structural-mutation revision (R4Agent cache invalidation)."""
        with self._lock:
            return self._revision

    def delete(self, name: str, agent_id: str = "", role: str = "", internal: bool = False) -> dict:
        """Delete a skill from the runtime registry (developer-only).

        ``internal=True`` allows identity-less deletes from system processes
        (R4Agent TTL pruning); external callers must pass an identity.
        """
        ok, who = self.authorize_write(agent_id, role, internal=internal)
        if not ok:
            return {"success": False, "error": f"permission denied: {who}"}
        with self._lock:
            if name not in self._skills:
                return {"success": False, "error": f"skill '{name}' not found"}
            if self._skills[name].get("builtin"):
                return {"success": False, "error": f"permission denied: builtin skill '{name}' is read-only"}
            del self._skills[name]
            self._revision += 1
            self._drop_skill_from_cells(name)
            self._emit_mutated("delete", name, agent_id, who)
            return {"success": True, "skill": name, "authorized": who}

    @staticmethod
    def _emit_mutated(action: str, name: str, agent_id: str, who: str) -> None:
        """Emit an EVENT_SKILL_MUTATED audit signal (best-effort, lazy import)."""
        try:
            from l1.kernel.event import get_bus
            from l1.kernel.params.agent import EVENT_SKILL_MUTATED

            # String-typed emit registers the custom signal type on first use
            # (emit_signal would KeyError on the unregistered type lookup).
            get_bus().emit_event(EVENT_SKILL_MUTATED, data={"action": action, "skill": name}, source=agent_id or who)
        except Exception:
            # Audit is best-effort — never break the mutation on signal failure.
            logger.debug("skill: mutation audit signal failed (best-effort)", exc_info=True)


_manager: SkillManager | None = None
_manager_lock = threading.Lock()


# ── Audience routing (domain-based skill supply) ──
# Skills carry audience tags ("strategy" / "execution"); the audience of an
# agent is derived from its identity. Strategy skills serve the L3A central
# layer (policy flow); execution skills serve Cell peer agents (execution
# flow). Untagged skills are universal. This powers dynamic supply through
# use_skill (on-demand) instead of context injection.
_AUDIENCE_TAGS: Final[tuple[str, ...]] = ("strategy", "execution")
_AUDIENCE_STRATEGY_AGENTS: Final[frozenset[str]] = frozenset({"l3a"})

# ── Skill→memory feedback hooks (P1-③) ──
# L3's skill-memory feedback module registers its batcher here; L1 never
# imports upper layers — the hook keeps the dependency direction L3 → L1.
_USAGE_FEEDBACK_HOOKS: list[Callable[[str], None]] = []


def register_usage_feedback_hook(fn: Callable[[str], None]) -> None:
    """Register a skill-usage feedback hook (L3 skill-memory feedback)."""
    if fn not in _USAGE_FEEDBACK_HOOKS:
        _USAGE_FEEDBACK_HOOKS.append(fn)


def audience_of(agent_id: str) -> str:
    """Audience domain for an agent: strategy (L3A) or execution (others)."""
    return "strategy" if agent_id in _AUDIENCE_STRATEGY_AGENTS else "execution"


def skill_visible(skill: dict, agent_id: str) -> bool:
    """Whether a skill is visible to an agent under audience routing.

    Untagged skills (system knowledge) are universal; a tagged skill is
    visible only to its own audience.
    """
    tags = set(skill.get("tags") or [])
    tagged = tags & set(_AUDIENCE_TAGS)
    if not tagged:
        return True
    return audience_of(agent_id) in tagged


def get_skill_manager() -> SkillManager:
    """Get the skill manager singleton (lazily created)."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = SkillManager()
    return _manager


def reset_skill_manager() -> None:
    """Reset the skill manager singleton to None (for tests / hot reset)."""
    global _manager
    _manager = None
