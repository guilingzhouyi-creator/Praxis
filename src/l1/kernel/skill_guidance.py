"""SkillGuidanceMixin — quest-style staged skills + guidance DAG for SkillManager.

Extracted from skill.py.  The mixin owns per-session stage state
(``self._stage_state``) and the guidance graph (dependencies/next edges);
the concrete ``SkillManager`` composes it with the policy/persist/retrieval
mixins and owns the shared registry (``self._skills``).
"""

from __future__ import annotations

import logging
import threading
import time

from .params.system import SKILL_STAGE_PRUNE_INTERVAL, SKILL_STAGE_STATE_TTL

logger = logging.getLogger(__name__)


class SkillGuidanceMixin:
    """SkillGuidanceMixin — staged-skill progression and guided-path engine."""

    # ── Attributes injected by the concrete SkillManager (see skill.py) ──
    _lock: threading.RLock
    _skills: dict[str, dict]
    _guidance_mode: str
    _stage_state: dict[tuple[str, str], int]
    _stage_touched: dict[tuple[str, str], float]
    _last_stage_prune: float = 0.0

    def _prune_stage_state_locked(self, now: float) -> None:
        """Drop stage-state entries untouched for SKILL_STAGE_STATE_TTL.

        Debounced by SKILL_STAGE_PRUNE_INTERVAL so the hot path does not
        scan the whole dict on every call. Caller must hold ``self._lock``.
        """
        if now - self._last_stage_prune < SKILL_STAGE_PRUNE_INTERVAL:
            return
        self._last_stage_prune = now
        stale = [key for key, touched in self._stage_touched.items() if now - touched >= SKILL_STAGE_STATE_TTL]
        for key in stale:
            self._stage_state.pop(key, None)
            self._stage_touched.pop(key, None)

    def current_stage(self, name: str, session_key: str = "") -> dict:
        """Return the active stage of a staged skill for a session.

        Unstaged skills return ``staged: False``. The stage index is
        per-session (session_key, typically the agent/card id) so parallel
        sessions never interfere.
        """
        skill = self._skills.get(name)
        stages = skill.get("stages") if skill else None
        if self._guidance_mode == "small" or not stages:
            return {"skill": name, "staged": False, "stage": None}
        with self._lock:
            self._prune_stage_state_locked(time.time())
            idx = self._stage_state.get((name, session_key), 0)
            # Register only card-scoped sessions: on_card_complete consumes
            # "card:" keys exclusively, so registering bare agent ids here
            # would grow _stage_state forever without ever being advanced
            # (unbounded singleton growth + dead entries).
            if session_key.startswith("card:"):
                self._stage_state.setdefault((name, session_key), 0)
                self._stage_touched.setdefault((name, session_key), time.time())
        idx = max(0, min(idx, len(stages) - 1))
        stage = stages[idx]
        return {
            "skill": name,
            "staged": True,
            "stage_index": idx,
            "stage": stage,
            "next_stage": stages[idx + 1].get("id") if idx + 1 < len(stages) else None,
            "done": idx >= len(stages) - 1,
        }

    def advance_stage(self, name: str, session_key: str = "") -> dict:
        """Advance a staged skill to its next stage for a session."""
        skill = self._skills.get(name)
        stages = skill.get("stages") if skill else None
        if self._guidance_mode == "small" or not stages:
            return {"success": True, "skill": name, "staged": False}
        with self._lock:
            self._prune_stage_state_locked(time.time())
            idx = self._stage_state.get((name, session_key), 0)
            if idx < len(stages) - 1:
                idx += 1
                self._stage_state[(name, session_key)] = idx
                self._stage_touched[(name, session_key)] = time.time()
            return {
                "success": True,
                "skill": name,
                "stage_index": idx,
                "done": idx >= len(stages) - 1,
            }

    # ── Guided-path engine (quest-style skill chain) ──

    def _guidance_graph(self) -> dict[str, set[str]]:
        """Build the skill guidance DAG: skill → set of skills it unlocks.

        Edges come from both directions: a skill's ``dependencies`` (prereq
        skills that must be satisfied) and ``next`` (forward guidance). The
        graph is rebuilt lazily per call — the registry is small.
        """
        graph: dict[str, set[str]] = {}
        with self._lock:
            for name, skill in self._skills.items():
                deps = [d for d in (skill.get("dependencies") or []) if isinstance(d, str)]
                for d in deps:
                    graph.setdefault(d, set()).add(name)
                nxt = [n for n in (skill.get("next") or []) if isinstance(n, str)]
                for n in nxt:
                    graph.setdefault(name, set()).add(n)
        return graph

    def validate_guidance_graph(self) -> dict:
        """Detect cycles in the skill guidance DAG (fail-fast on edits)."""
        graph = self._guidance_graph()
        white, gray, black = 0, 1, 2
        color: dict[str, int] = {}
        stack: list[str] = []
        cycles: list[list[str]] = []

        def dfs(node: str) -> None:
            """Depth-first walk marking gray on entry and black on exit."""
            color[node] = gray
            stack.append(node)
            for nxt in graph.get(node, ()):
                if color.get(nxt, white) == white:
                    dfs(nxt)
                elif color.get(nxt) == gray:
                    idx = stack.index(nxt) if nxt in stack else 0
                    cycles.append(stack[idx:] + [nxt])
            stack.pop()
            color[node] = black

        for node in graph:
            if color.get(node, white) == white:
                dfs(node)
        return {"acyclic": not cycles, "cycles": cycles, "nodes": len(graph)}

    def guided_frontier(self, completed: list[str] | None = None) -> list[str]:
        """Return the currently unlocked skills (quest-log frontier).

        In small guidance mode every visible skill is unlocked (guidance
        fields inert). In full mode a skill is unlocked when all its
        dependency prerequisites are satisfied (in ``completed``).
        """
        if self._guidance_mode == "small":
            with self._lock:
                items = list(self._skills.items())
            return sorted(n for n, s in items if s.get("disclosure", "full") != "none")
        completed_set = set(completed or [])
        frontier: list[str] = []
        with self._lock:
            for name, skill in self._skills.items():
                if skill.get("disclosure", "full") == "none":
                    continue
                deps = [d for d in (skill.get("dependencies") or []) if isinstance(d, str)]
                if all(d in completed_set for d in deps):
                    frontier.append(name)
        frontier.sort()
        return frontier

    def guided_path(self, target: str) -> list[str]:
        """Reverse-chain the prerequisite path to *target* (BFS over deps)."""
        with self._lock:
            deps_of = {
                name: [d for d in (skill.get("dependencies") or []) if isinstance(d, str)]
                for name, skill in self._skills.items()
            }
        chain: list[str] = []
        seen: set[str] = set()
        queue: list[str] = [target]
        while queue:
            node = queue.pop(0)
            if node in seen or node not in self._skills:
                continue
            seen.add(node)
            chain.append(node)
            queue.extend(deps_of.get(node, []))
        chain.reverse()
        return chain

    def on_card_complete(self, card_id: str, state: str = "", result: dict | None = None) -> dict:
        """Advance staged skills bound to a card session (three-table linkage).

        Called by the card completion listener (see l3.memory.skill_guidance);
        advances the stage state of every staged skill used under this card's
        session key. Returns the number of stages advanced.
        """
        if state and state.upper() not in ("COMPLETED", "DONE"):
            return {"advanced": 0}
        if self._guidance_mode == "small":
            return {"advanced": 0}
        session_key = f"card:{card_id}"
        advanced = 0
        with self._lock:
            self._prune_stage_state_locked(time.time())
            for (name, key), idx in list(self._stage_state.items()):
                if key != session_key:
                    continue
                skill = self._skills.get(name)
                stages = skill.get("stages") if skill else None
                if stages and idx < len(stages) - 1:
                    self._stage_state[(name, key)] = idx + 1
                    self._stage_touched[(name, key)] = time.time()
                    advanced += 1
        return {"advanced": advanced, "session_key": session_key}
