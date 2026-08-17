"""DVG — declarative tool dependency graph (DAG).

Maps tool names to their prerequisite tools so execution order and
availability can be validated ahead of dispatch. Declared in
``config/discovery/dvg.yaml`` and registered at boot; also mutable at
runtime via the module-level API.

The graph is a DAG: a cycle (A needs B, B needs A) is detected on
registration and rejected. Consumers (tool pipeline preflight, parallel
matrix ordering) read the read-only views without locking, since the
graph is only mutated at boot / by explicit admin calls.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

# Singleton (reset in tests via reset_dvg)
_dvg: DvgGraph | None = None
_dvg_lock = threading.RLock()


class DvgGraph:
    """Declarative tool dependency graph with cycle detection."""

    def __init__(self) -> None:
        self._deps: dict[str, list[str]] = {}
        self._lock = threading.RLock()
        self._revision = 0
        self._plan_cache: dict[str, tuple[int, list[str]]] = {}

    # ── Mutations ──

    def register_tool_deps(self, name: str, deps: list[str]) -> bool:
        """Register a tool and its prerequisite tools.

        Returns False (and logs) when adding the edge would create a
        cycle — the tool's existing edges are left unchanged.
        """
        started = time.perf_counter()
        deps = [d for d in deps if d and d != name]
        result = False
        try:
            with self._lock:
                if name in self._deps and sorted(self._deps[name]) == sorted(deps):
                    result = True
                else:
                    prev = self._deps.get(name, [])
                    self._deps[name] = list(deps)
                    if self._find_cycle(name):
                        # Roll back: the new edges created a cycle.
                        if prev:
                            self._deps[name] = prev
                        else:
                            self._deps.pop(name, None)
                        logger.warning("dvg: rejecting deps for '%s' — would create a cycle", name)
                    else:
                        self._revision += 1
                        self._plan_cache.clear()
                        result = True
        finally:
            from l3.services.observability import emit_count, emit_duration

            tags = {"tool": name, "success": result}
            emit_duration("dvg.register.duration_ms", started, tags=tags)
            emit_count("dvg.register.count", tags=tags)
        return result

    def unregister(self, name: str) -> bool:
        """Drop a tool node and all edges referencing it."""
        with self._lock:
            removed = self._deps.pop(name, None) is not None
            changed = removed
            for node, deps in list(self._deps.items()):
                if name in deps:
                    self._deps[node] = [d for d in deps if d != name]
                    changed = True
            if changed:
                self._revision += 1
                self._plan_cache.clear()
            return removed

    def clear(self) -> None:
        """Drop all edges (used at boot before loading the YAML)."""
        with self._lock:
            if self._deps:
                self._deps.clear()
                self._revision += 1
                self._plan_cache.clear()

    # ── Read-only views ──

    def deps_of(self, name: str) -> list[str]:
        """Return the direct prerequisites of a tool (stable order)."""
        with self._lock:
            return list(self._deps.get(name, []))

    def dependents_of(self, name: str) -> list[str]:
        """Return tools that list *name* as a prerequisite."""
        with self._lock:
            return sorted(n for n, deps in self._deps.items() if name in deps)

    def all_names(self) -> list[str]:
        """Return all registered tool names, sorted."""
        with self._lock:
            return sorted(self._deps.keys())

    def can_run(self, name: str) -> bool:
        """True when all transitive prerequisites are registered."""
        with self._lock:
            return bool(self.execution_plan(name))

    def execution_plan(self, name: str) -> list[str]:
        """Return prerequisites-first execution order for one tool.

        An empty result means a prerequisite is missing or a cycle was found.
        Tools without a DVG node still produce a one-item plan, which keeps
        ordinary builtin dispatch backward compatible.
        """
        started = time.perf_counter()
        plan: list[str] = []
        cache_hit = False
        try:
            with self._lock:
                cached = self._plan_cache.get(name)
                if cached is not None and cached[0] == self._revision:
                    plan = list(cached[1])
                    cache_hit = True
                else:
                    order: list[str] = []
                    visiting: set[str] = set()
                    visited: set[str] = set()

                    def visit(node: str) -> bool:
                        if node in visited:
                            return True
                        if node in visiting:
                            return False
                        visiting.add(node)
                        if node in self._deps:
                            for dep in self._deps[node]:
                                if dep not in self._deps or not visit(dep):
                                    return False
                        visiting.remove(node)
                        visited.add(node)
                        order.append(node)
                        return True

                    plan = order if visit(name) else []
                    self._plan_cache[name] = (self._revision, list(plan))
        finally:
            from l3.services.observability import emit_count, emit_duration

            tags = {"tool": name, "success": bool(plan)}
            emit_duration("dvg.plan.duration_ms", started, tags=tags)
            emit_count("dvg.plan.nodes", len(plan), tags={"tool": name})
            emit_count("dvg.plan.cache_hit", int(cache_hit), tags={"tool": name})
        return plan

    def _walk(self, name: str, seen: set[str]) -> bool:
        """DFS availability check with cycle guard."""
        if name in seen:
            return True  # already visited on this path
        seen.add(name)
        for dep in self._deps.get(name, []):
            if dep not in self._deps:
                return False  # prerequisite not registered
            if not self._walk(dep, seen):
                return False
        return True

    def topo_order(self) -> list[str]:
        """Return a topological order (prerequisites first); empty on cycle."""
        with self._lock:
            order: list[str] = []
            visited: set[str] = set()
            temp: set[str] = set()

            def visit(node: str) -> bool:
                """DFS visit for topological sort; False marks a cycle."""
                if node in visited:
                    return True
                if node in temp:
                    return False  # cycle
                temp.add(node)
                for dep in self._deps.get(node, []):
                    if not visit(dep):
                        return False
                temp.discard(node)
                visited.add(node)
                order.append(node)
                return True

            for node in sorted(self._deps.keys()):
                if not visit(node):
                    return []
            return order

    def cycles(self) -> list[list[str]]:
        """Return detected cycles as node lists (empty when the graph is a DAG)."""
        with self._lock:
            found: list[list[str]] = []
            for node in self._deps:
                for neighbor in self._deps.get(node, []):
                    if self._reachable(neighbor, node, set()):
                        found.append([node, neighbor])
            # Dedup reversed pairs
            uniq: list[list[str]] = []
            for c in found:
                if [c[1], c[0]] not in uniq:
                    uniq.append(c)
            return uniq

    def _reachable(self, start: str, target: str, seen: set[str]) -> bool:
        """Whether *target* is reachable from *start*."""
        if start == target:
            return True
        if start in seen:
            return False
        seen.add(start)
        return any(self._reachable(d, target, seen) for d in self._deps.get(start, []))

    def _find_cycle(self, start: str) -> bool:
        """Whether *start* participates in a cycle."""
        return any(self._reachable(d, start, set()) for d in self._deps.get(start, []))

    def to_dict(self) -> dict:
        """Serializable view for status endpoints."""
        with self._lock:
            return {n: list(d) for n, d in self._deps.items()}


def get_dvg() -> DvgGraph:
    """Get the global DVG singleton."""
    global _dvg
    with _dvg_lock:
        if _dvg is None:
            _dvg = DvgGraph()
        return _dvg


def reset_dvg() -> None:
    """Reset the singleton (used by tests)."""
    global _dvg
    with _dvg_lock:
        _dvg = None
