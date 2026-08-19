"""SkillRetrievalMixin — lean-case / evolved-skill retrieval surface.

Extracted from r4_skill_feedback.py (SkillFeedbackMixin): the injection
retrieval surface (get_lean_cases / get_lean_case_names /
get_evolved_skills / retrieve_skills) plus the card-tag gate helper.
Composed by SkillFeedbackMixin.
"""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel.params.agent import (
    R4_CARD_TAG_PREFIX,
    R4_EVOLVED_SKILLS_DEFAULT,
    R4_LEAN_CASES_DEFAULT,
    R4_RETRIEVAL_ENABLED,
    R4_RETRIEVAL_MIN_SCORE,
)
from l1.kernel.params.system import SKILL_LIST_SCAN_LIMIT, SKILL_POSTURE_DEFAULT


def _system_permits_posture(skill_posture: str) -> bool:
    """Return whether the current system posture permits injecting a skill.

    Posture linkage (§11.4): under the productive posture only productive
    skills are exposed; offensive skills require the attack posture
    (security-test, confirmed). Read-only, best-effort — if the security
    posture cannot be resolved we fail closed (productive filter applies).
    """
    try:
        from l3.tool_system.security_mode import get_posture

        posture = get_posture()
        classification = str(posture.get("classification", "productive"))
    except Exception:
        classification = "productive"
    if skill_posture == "offensive":
        return classification == "attack"
    return True


def link_registered_skill_graph(sm, name: str, scope: str, tags: list[str]) -> dict:
    """Register-time R5 linkage (L3 entry point).

    Connect the new custom skill to related skill domains via semantic
    edges (``related``). Degrades to a no-op when the graph is disabled —
    registration never hard-fails on linkage. Kept in L3 so L2/API callers
    never import the memory graph directly (layer-import gate).
    """
    linked = 0
    try:
        from l3.memory.memory_graph import get_graph

        graph = get_graph()
        if graph is None or not getattr(graph, "enabled", False):
            return {"success": True, "skill": name, "scope": scope, "linked": 0}
        for candidate in sm.list_skills(tags=tags, limit=SKILL_LIST_SCAN_LIMIT, include_prompt=False):
            if candidate["name"] == name:
                continue
            edge = graph.add_semantic_edge(name, candidate["name"], "related", weight=0.8, created_by="register")
            if edge.get("success"):
                linked += 1
        return {"success": True, "skill": name, "scope": scope, "linked": linked}
    except Exception:
        return {"success": True, "skill": name, "scope": scope, "linked": 0}


logger = logging.getLogger(__name__)


def _passes_card_tags(skill: dict, tags: list[str] | None) -> bool:
    """Card-tag gate: untagged skills are universal; tagged skills must match.

    ``tags`` are OR-matched against the skill's ``card:*`` tags.  A skill
    carrying no ``card:*`` tag passes regardless (system knowledge stays
    visible to every card type); a skill tagged for another card type is
    excluded from this card's retrieval.
    """
    if not tags:
        return True
    skill_tags = set(skill.get("tags") or [])
    tagged = {t for t in skill_tags if t.startswith(R4_CARD_TAG_PREFIX)}
    if not tagged:
        return True
    return bool(tagged & set(tags))


class SkillRetrievalMixin:
    """Lean-case and evolved-skill retrieval for AgentLoop injection."""

    # Host-provided attributes (declared by R4Agent)
    _graph_diffuse_evolved: Any
    _skill_cache: Any

    def get_lean_cases(
        self, agent_id: str = "", tool_name: str = "", cell_id: str = "", limit: int = R4_LEAN_CASES_DEFAULT
    ) -> list[str]:
        """Retrieve lean failure cases for injection into AgentLoop prompts.

        When ``cell_id`` has a bound skill white-list (via SkillManager
        cell_skill_map), only lean cases whose name is in the white-list are
        returned; unbound cells fall back to the global pool.
        """
        from l1.kernel.skill import get_skill_manager

        sm = get_skill_manager()
        cache_key = ("lean", agent_id, tool_name, cell_id, limit)
        rev = sm.revision()
        cached = self._skill_cache.get(cache_key)
        if cached and cached[0] == rev:
            return cached[1]
        tags = ["lean_case"]
        if agent_id:
            tags.append(agent_id)
        if tool_name:
            tags.append(tool_name)
        skills = sm.list_skills(tags=tags, limit=limit * 2, sort_by="loaded_at", include_prompt=True)
        allow = sm.skills_for_cell(cell_id) if cell_id else set()
        result = []
        names = []
        for s in skills:
            if allow and s["name"] not in allow:
                continue
            if s.get("prompt"):
                names.append(s["name"])
                result.append(s["prompt"])
            if len(result) >= limit:
                break
        result = result[:limit]
        names = names[:limit]
        self._skill_cache[cache_key] = (rev, result, names)
        return result

    def get_lean_case_names(
        self, agent_id: str = "", tool_name: str = "", cell_id: str = "", limit: int = R4_LEAN_CASES_DEFAULT
    ) -> list[str]:
        """Return the skill names behind the lean cases get_lean_cases() yields.

        Shares the injection cache with get_lean_cases() so the AgentLoop can
        refresh ``last_used`` for exactly the cases it injected — no extra
        registry scan.
        """
        from l1.kernel.skill import get_skill_manager

        sm = get_skill_manager()
        cache_key = ("lean", agent_id, tool_name, cell_id, limit)
        rev = sm.revision()
        cached = self._skill_cache.get(cache_key)
        if cached and cached[0] == rev and len(cached) >= 3:
            return cached[2]
        # Cache miss or stale — repopulate through get_lean_cases().
        self.get_lean_cases(agent_id, tool_name, cell_id, limit)
        cached = self._skill_cache.get(cache_key)
        return cached[2] if cached and len(cached) >= 3 else []

    def get_evolved_skills(
        self,
        agent_id: str = "",
        cell_id: str = "",
        role: str = "",
        limit: int = R4_EVOLVED_SKILLS_DEFAULT,
        graph_diffusion: bool = False,
        tags: list[str] | None = None,
    ) -> list[dict]:
        """Retrieve evolved skills for injection into AgentLoop prompts.

        Filters by agent_id if provided (strict tag membership, not OR-match).
        When ``cell_id`` has a bound white-list, only white-listed skills are
        returned (unbound cells fall back to the global pool).  ``tags`` are
        OR-matched against the skill's tags (card-nature linkage: skills
        tagged ``card:<nature>`` surface only for cards of that nature).
        Returns most recently loaded skills first.
        """
        from l1.kernel.skill import get_skill_manager

        sm = get_skill_manager()
        cache_key = ("evolved", agent_id, cell_id, role, limit, graph_diffusion, tuple(tags or ()))
        rev = sm.revision()
        cached = self._skill_cache.get(cache_key)
        if cached and cached[0] == rev:
            return cached[1]
        allow = sm.skills_for_cell(cell_id) if cell_id else set()
        if graph_diffusion:
            try:
                diffused = self._graph_diffuse_evolved(limit=limit)
                if diffused:
                    evolved = []
                    for name in diffused:
                        s = sm.get(name)
                        if s and s.get("prompt"):
                            if allow and name not in allow:
                                continue
                            if not _passes_card_tags(s, tags):
                                continue
                            if not _system_permits_posture(str(s.get("posture", SKILL_POSTURE_DEFAULT))):
                                continue
                            if not sm.skill_is_injectable(s, agent_id, cell_id, role, tags):
                                continue
                            evolved.append(
                                {
                                    "name": s["name"],
                                    "description": s.get("description", ""),
                                    "prompt": s["prompt"],
                                    "posture": s.get("posture", SKILL_POSTURE_DEFAULT),
                                    "binding": s.get("binding") or {},
                                    "status": s.get("status", "active"),
                                    "scope": s.get("scope", ""),
                                    "scope_identity": s.get("scope_identity", ""),
                                    "priority": int(s.get("priority", 0) or 0),
                                }
                            )
                    if evolved:
                        evolved.sort(key=lambda s: -int(s.get("priority", 0) or 0))
                        return evolved[:limit]
            except Exception as e:
                logger.debug("R4Agent: graph diffusion fallback to linear: %s", e)
        skills = sm.list_skills(tags=["evolved"], limit=limit * 2, sort_by="loaded_at", include_prompt=True)
        evolved = []
        for s in skills:
            binding = s.get("binding") or {}
            has_explicit_binding = (
                any(binding.get(key) for key in ("cell_ids", "roles", "agent_ids", "card_natures"))
                if isinstance(binding, dict)
                else False
            )
            # Legacy evolved skills use an agent tag as their scope.  An
            # explicit Cell/role/card binding supersedes that legacy filter;
            # skill_is_injectable() performs the authoritative scope check.
            if agent_id and not has_explicit_binding and agent_id not in s.get("tags", []):
                continue
            if allow and s["name"] not in allow:
                continue
            if not _passes_card_tags(s, tags):
                continue
            if not _system_permits_posture(str(s.get("posture", SKILL_POSTURE_DEFAULT))):
                continue
            if not sm.skill_is_injectable(s, agent_id, cell_id, role, tags):
                continue
            if s.get("prompt"):
                evolved.append(
                    {
                        "name": s["name"],
                        "description": s.get("description", ""),
                        "prompt": s["prompt"],
                        "posture": s.get("posture", SKILL_POSTURE_DEFAULT),
                        "binding": s.get("binding") or {},
                        "status": s.get("status", "active"),
                        "scope": s.get("scope", ""),
                        "scope_identity": s.get("scope_identity", ""),
                        "priority": int(s.get("priority", 0) or 0),
                    }
                )
        # Priority conflict resolution (§11.1): custom skills outrank
        # builtin/evolved on equal relevance — sort descending by priority
        # so higher-priority skills surface first (builtins pin 0).
        evolved.sort(key=lambda s: -int(s.get("priority", 0) or 0))
        evolved = evolved[:limit]
        self._skill_cache[cache_key] = (rev, evolved)
        return evolved

    def retrieve_skills(
        self,
        query: str = "",
        agent_id: str = "",
        cell_id: str = "",
        role: str = "",
        limit: int = R4_EVOLVED_SKILLS_DEFAULT,
        graph_diffusion: bool = False,
        tags: list[str] | None = None,
    ) -> list[dict]:
        """Retrieve evolved skills ranked by task-text similarity.

        Delegates ranking to the pluggable retriever backend (``tfidf`` by
        default, see ``l3.memory.skill_retriever``).  Gated by
        ``R4_RETRIEVAL_ENABLED``; when disabled, query is empty, or no
        candidate clears the similarity floor, it falls back to
        ``get_evolved_skills`` ordering (most recently loaded first).
        ``tags`` are forwarded as an OR-match filter (card-nature linkage).
        """
        # Runtime policy (SkillManager pipeline policy) overrides the
        # compile-time defaults — retrieval can be disabled or its similarity
        # floor tuned per-deployment via API / L2 Shell, not just params.
        policy = {}
        try:
            from l1.kernel.skill import get_skill_manager

            policy = get_skill_manager().pipeline_policy()
        except Exception:
            pass
        retrieval_enabled = bool(policy.get("retrieval", R4_RETRIEVAL_ENABLED))
        min_score = float(policy.get("retrieval_min_score", R4_RETRIEVAL_MIN_SCORE))
        if not retrieval_enabled or not query:
            return self.get_evolved_skills(
                agent_id=agent_id,
                cell_id=cell_id,
                role=role,
                limit=limit,
                graph_diffusion=graph_diffusion,
                tags=tags,
            )
        base = self.get_evolved_skills(
            agent_id=agent_id,
            cell_id=cell_id,
            role=role,
            limit=limit * 4,
            graph_diffusion=graph_diffusion,
            tags=tags,
        )
        if not base:
            return []
        # Disclosure depth: skills marked disclosure=none never surface in
        # task-similarity retrieval (explicit use_skill only).
        base = [s for s in base if s.get("disclosure", "full") != "none"]
        if not base:
            return []
        # Builtin skills join the task-similarity pool (audience + disclosure
        # filtered) so retrieval covers the full catalog, not just evolved.
        try:
            from l1.kernel.skill import get_skill_manager as _loop_sm
            from l1.kernel.skill import skill_visible as _sv

            # Full guidance mode: skills with *unmet hard dependencies* stay
            # out of the retrieval pool; soft dependencies are advisory and
            # never lock a skill (no builtin declares hard deps, so the pool
            # keeps full coverage by default).
            _hard_locked = set()
            if _loop_sm().guidance_policy().get("mode", "full") == "full":
                for s2 in _loop_sm().list_skills():
                    if s2.get("dependency_kind", "soft") == "hard" and (s2.get("dependencies") or []):
                        _hard_locked.add(s2.get("name"))
            for s in _loop_sm().list_skills(include_prompt=True):
                if not s.get("builtin"):
                    continue
                if s.get("disclosure", "full") == "none":
                    continue
                if not _sv(s, agent_id):
                    continue
                if s.get("name") in _hard_locked:
                    continue
                if s not in base:
                    base.append(s)
        except Exception:
            pass
        if not base:
            return []
        from l3.memory.skill_retriever import get_retriever

        ranked = get_retriever().rank(query, base, limit=limit, min_score=min_score)
        return ranked if ranked else base[:limit]
