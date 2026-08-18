"""SkillRetrievalMixin — query/list/projection surfaces for SkillManager.

Extracted from skill.py.  The mixin owns the agent-facing read surfaces
(keyword query, VFS content, catalog listing, rule aggregation and the
structured skill projection); the concrete ``SkillManager`` composes it
with the policy/guidance/persist mixins and owns the shared registry.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from l1.kernel.params.system import (
    LOG_TRUNC_50,
    LOG_TRUNC_60,
    LOG_TRUNC_2000,
    SKILL_DISCLOSURE_DEFAULT,
    SKILL_POSTURE_DEFAULT,
    SKILL_STATUS_DEFAULT,
)

logger = logging.getLogger(__name__)


class SkillRetrievalMixin:
    """SkillRetrievalMixin — query, VFS content, catalog listing, structured view."""

    # ── Attributes injected by the concrete SkillManager (see skill.py) ──
    _lock: threading.RLock
    _skills: dict[str, dict]
    _revision: int

    # ── Methods provided by SkillGuidanceMixin (see skill_guidance.py) ──
    current_stage: Callable[[str, str], dict]

    def get(self, name: str) -> dict | None:
        """Return the skill record for *name*, or None."""
        with self._lock:
            return self._skills.get(name)

    def structured_skill(self, name: str, session_key: str = "") -> dict:
        """Return a skill as pure structure — the agent-facing view.

        The human-readable SKILL.md stays the source of truth; this
        projection (rules/procedures/stages as machine-readable items plus
        the current stage) is what the agent consumes at runtime — the raw
        markdown body is excluded (full content stays on the human/review
        layer).
        """
        skill = self._skills.get(name)
        if not skill:
            return {"success": False, "error": f"skill '{name}' not found"}
        stage = None
        if skill.get("stages"):
            stage = self.current_stage(name, session_key)
        return {
            "success": True,
            "name": name,
            "description": skill.get("description", ""),
            "rules": list(skill.get("rules") or []),
            "procedures": list(skill.get("procedures") or []),
            "allowed_tools": skill.get("allowed_tools") or [],
            "variables": skill.get("variables") or [],
            "dependencies": skill.get("dependencies") or [],
            "next": skill.get("next") or [],
            "disclosure": skill.get("disclosure", SKILL_DISCLOSURE_DEFAULT),
            "binding": dict(skill.get("binding") or {}),
            "status": skill.get("status") or SKILL_STATUS_DEFAULT,
            "stage": stage,
        }

    # ── Layered index (P0-②) ──
    # layer -> set(skill names): rebuilt lazily on revision change so
    # per-layer listing avoids a full registry scan on every call.
    _layer_index: dict[str, set[str]] | None = None
    _layer_index_rev: int = -1

    def _layer_names(self, layer: str) -> set[str]:
        """Names of skills in a generalization layer (revision-cached)."""
        try:
            rev = self._revision
        except AttributeError:
            rev = -1
        with self._lock:
            if self._layer_index is None or self._layer_index_rev != rev:
                index: dict[str, set[str]] = {}
                for n, s in self._skills.items():
                    key = str(s.get("layer", "") or "")
                    if key:
                        index.setdefault(key, set()).add(n)
                self._layer_index = index
                self._layer_index_rev = rev
            return set(self._layer_index.get(layer, set()))

    def list_skills(
        self,
        tags: list[str] | None = None,
        limit: int = 0,
        sort_by: str = "name",
        include_prompt: bool = False,
        layer: str = "",
    ) -> list[dict]:
        """List skills, optionally filtered by tags/layer and sorted.

        Args:
            tags: Filter by these tags (any match).
            limit: Max results (0 = unlimited).
            sort_by: Sort key: ``"name"`` (default), ``"loaded_at"``, ``"last_used"``.
            include_prompt: include the full prompt in each projection.
            layer: Filter by generalization layer (``"exec"`` /
                ``"decision"`` / other; "" = all). The layer index is
                rebuilt lazily on revision change, so per-layer listing
                stays O(layer size) instead of a full registry scan.
        """
        with self._lock:
            items = list(self._skills.items())
        if layer:
            names = self._layer_names(layer)
            items = [(n, s) for n, s in items if n in names]
        result = []
        for n, s in items:
            if tags:
                skill_tags = s.get("tags", [])
                if not any(t in skill_tags for t in tags):
                    continue
            result.append(
                {
                    "name": n,
                    "description": s.get("description", "")[:LOG_TRUNC_60],
                    "rules": len(s.get("rules", [])),
                    "procedures": len(s.get("procedures", [])),
                    "tags": s.get("tags", []),
                    "prompt": s.get("prompt", "") if include_prompt else "",
                    "source": s.get("source", ""),
                    "builtin": bool(s.get("builtin")),
                    "posture": s.get("posture", SKILL_POSTURE_DEFAULT),
                    "binding": dict(s.get("binding") or {}),
                    "status": s.get("status") or SKILL_STATUS_DEFAULT,
                    "disclosure": s.get("disclosure", SKILL_DISCLOSURE_DEFAULT),
                    "stages": len(s.get("stages") or []),
                    "next": s.get("next") or [],
                    "loaded_at": s.get("loaded_at", 0.0),
                    "last_used": s.get("last_used", 0.0),
                    "disable_model_invocation": bool(s.get("disable_model_invocation")),
                    "dependencies": s.get("dependencies", []),
                    "dependency_kind": s.get("dependency_kind", "soft"),
                    "scope": s.get("scope", ""),
                    "scope_identity": s.get("scope_identity", ""),
                    "priority": int(s.get("priority", 0) or 0),
                }
            )
        if sort_by == "loaded_at":
            result.sort(key=lambda x: -x["loaded_at"])
        elif sort_by == "last_used":
            result.sort(key=lambda x: -x["last_used"])
        else:
            result.sort(key=lambda x: x["name"])
        if limit > 0:
            result = result[:limit]
        return result

    def rules_for(self, domain: str = "") -> list[str]:
        """Get all rules matching a domain (e.g., 'python', 'go', 'review')."""
        domain_lower = domain.lower()
        rules = []
        with self._lock:
            for name, skill in self._skills.items():
                if domain_lower and domain_lower not in name.lower():
                    continue
                rules.extend(skill.get("rules", []))
        return rules

    def list_by_allowed_tools(self, tool_name: str) -> list[dict]:
        """List skills that allow using a specific tool."""
        results = []
        with self._lock:
            for name, skill in self._skills.items():
                at = skill.get("allowed_tools")
                if at is None or tool_name in at:
                    results.append(
                        {
                            "name": name,
                            "description": skill.get("description", "")[:LOG_TRUNC_60],
                        }
                    )
        return results

    def query(self, question: str) -> list[dict]:
        """Query skills by keyword matching.

        Uses TF-IDF-like scoring: term frequency in name (weight 3),
        description (weight 2), rules (weight 1), and prompt (weight 0.5).
        """
        import re as _re

        q = question.lower().strip()
        if not q:
            return []
        terms = set(_re.split(r"[\s,;:._-]+", q))
        results: list[dict[str, Any]] = []
        with self._lock:
            for name, skill in self._skills.items():
                score = 0.0
                name_lower = name.lower()
                desc = skill.get("description", "").lower()
                prompt = (skill.get("prompt", "") or "")[:LOG_TRUNC_2000].lower()
                rules = [r.lower() for r in skill.get("rules", [])]
                for t in terms:
                    if not t:
                        continue
                    # Name hits (weight 3)
                    count = name_lower.count(t)
                    if count:
                        score += 3.0 * count
                    # Description hits (weight 2)
                    count = desc.count(t)
                    if count:
                        score += 2.0 * count
                    # Rules hits (weight 1)
                    for r in rules:
                        count = r.count(t)
                        if count:
                            score += 1.0 * count
                    # Prompt hits (weight 0.5)
                    count = prompt.count(t)
                    if count:
                        score += 0.5 * count
                if score > 0:
                    results.append({"name": name, "score": round(score, 1), "skill": skill})
        results.sort(key=lambda x: float(x["score"]), reverse=True)
        return results

    def skill_vfs_content(self) -> str:
        """Generate /skills/ virtual filesystem content."""
        lines = []
        for name in sorted(self._skills.keys()):
            skill = self._skills[name]
            desc = skill.get("description", "")[:LOG_TRUNC_50]
            rc = len(skill.get("rules", []))
            lines.append(f"{name:30s} {desc:50s} [{rc} rules]")
        return "\n".join(lines) if lines else "(no skills loaded)"
