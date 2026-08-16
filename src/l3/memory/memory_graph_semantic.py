"""MemoryGraph — LLM semantic edge extraction mixin.

Extracted from ``memory_graph.py``: the hybrid-mode semantic extraction
state machine behavior (pair picking + one LLM call per pair) with
auto-degrade to ``paused`` on engine failure. Composed by MemoryGraph.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from l1.kernel.params.system import LOG_TRUNC_300

from .memory_graph_constants import (
    _EDGE_MODE_HYBRID,
    _EDGE_MODE_PAUSED,
    _LLM_EXTRACT_MAX_PAIRS,
    _LLM_EXTRACT_MAX_TOKENS,
    _LLM_EXTRACT_MAX_WORKERS,
    _SEMANTIC_RELATIONS,
)

logger = logging.getLogger(__name__)


class SemanticExtractionMixin:
    """Hybrid-mode LLM semantic edge extraction — composed by MemoryGraph."""

    # Attributes/methods provided by the composing MemoryGraph (for mypy).
    _edge_mode: str
    _enabled: bool
    _conn: Any
    add_semantic_edge: Callable[..., Any]
    set_edge_mode: Callable[..., Any]

    def extract_semantic_edges(
        self, entries: list[dict], engine: Any = None, max_pairs: int = _LLM_EXTRACT_MAX_PAIRS
    ) -> dict:
        """LLM extracts contradicts/depends_on/refines between entry pairs.

        State machine: runs ONLY in hybrid mode. On LLM failure the mode
        auto-degrades to paused (governance: cost/failure control).

        Args:
            entries: [{"id", "entry_type", "content"}] — candidate entries
            engine:  injectable LLM engine (defaults to llm port)
        Returns: {"success", "added": N, "relations": [...], "mode": ...}
        """
        if self._edge_mode != _EDGE_MODE_HYBRID:
            return {"success": False, "added": 0, "error": f"edge_mode is {self._edge_mode}, not hybrid"}
        if not self._enabled or self._conn is None:
            return {"success": False, "added": 0, "error": "graph disabled"}
        candidates = [e for e in entries if e and e.get("id") and e.get("content")]
        if len(candidates) < 2:
            return {"success": True, "added": 0, "relations": [], "mode": self._edge_mode}
        try:
            engine = engine or self._resolve_llm_engine()
            pairs = self._pick_pairs(candidates, max_pairs)
            relations: list[dict] = []
            added = 0
            engine_failures = 0
            # Serial LLM calls per pair are the extraction hot path: fire the
            # pair questions concurrently (bounded by _LLM_EXTRACT_MAX_WORKERS)
            # while preserving deterministic pair order via executor.map.
            if len(pairs) > 1:
                with ThreadPoolExecutor(
                    max_workers=min(_LLM_EXTRACT_MAX_WORKERS, len(pairs)),
                    thread_name_prefix="mem-sem",
                ) as pool:
                    rels = list(pool.map(lambda p: self._ask_relation(engine, p[0], p[1]), pairs))
            else:
                rels = [self._ask_relation(engine, a, b) for a, b in pairs]
            for rel, (a, b) in zip(rels, pairs, strict=True):
                if rel is None:
                    engine_failures += 1
                    continue
                if rel in _SEMANTIC_RELATIONS:
                    r = self.add_semantic_edge(a["id"], b["id"], rel, created_by="llm")
                    if r.get("success"):
                        added += 1
                        relations.append({"from": a["id"], "to": b["id"], "relation": rel})
            if engine_failures and engine_failures == len(pairs):
                raise RuntimeError("LLM semantic extraction engine failed")
            return {"success": True, "added": added, "relations": relations, "mode": self._edge_mode}
        except Exception as e:
            # Auto-degrade: LLM failure → paused (manually recoverable)
            logger.warning("memory_graph: LLM semantic extract failed, edge_mode -> paused: %s", e)
            self.set_edge_mode(_EDGE_MODE_PAUSED)
            return {"success": False, "added": 0, "error": str(e), "mode": self._edge_mode}

    def _resolve_llm_engine(self):
        try:
            from l1.kernel.ports import get_port

            return get_port("llm")
        except Exception:
            from l4.llm.llm import get_engine

            return get_engine()

    def _pick_pairs(self, candidates: list[dict], max_pairs: int) -> list[tuple[dict, dict]]:
        """Pick the most informative pairs: same type (compare) + recent tail.

        Dedup uses a set keyed by entry ids — the naive ``(a, b) not in
        pairs`` list containment is O(n) per check (O(n²) overall).
        """
        pairs: list[tuple[dict, dict]] = []
        seen: set[tuple[str, str]] = set()
        by_type: dict[str, list[dict]] = {}
        for e in candidates:
            by_type.setdefault(e.get("entry_type", "?"), []).append(e)
        for group in by_type.values():
            if len(group) >= 2:
                pairs.append((group[-2], group[-1]))
                seen.add((group[-2].get("id", ""), group[-1].get("id", "")))
        for i in range(1, len(candidates)):
            if len(pairs) >= max_pairs:
                break
            a, b = candidates[i - 1], candidates[i]
            key = (a.get("id", ""), b.get("id", ""))
            if key not in seen and (key[1], key[0]) not in seen:
                seen.add(key)
                pairs.append((a, b))
        return pairs[:max_pairs]

    def _ask_relation(self, engine, a: dict, b: dict) -> str | None:
        """One LLM call: what is the semantic relation between A and B?

        Returns a relation keyword, "" (no relation), or None (engine fault).
        """
        from l1.kernel.prompts import get_prompt

        prompt = get_prompt("memory.graph.relation").format(
            a_type=a.get("entry_type", "?"),
            a_content=a.get("content", "")[:LOG_TRUNC_300],
            b_type=b.get("entry_type", "?"),
            b_content=b.get("content", "")[:LOG_TRUNC_300],
        )
        try:
            r = engine.generate(prompt, max_tokens=_LLM_EXTRACT_MAX_TOKENS)
            ans = (r.get("content", "") or "").strip().lower()
            for rel in _SEMANTIC_RELATIONS:
                if rel in ans:
                    return rel
            return ""
        except Exception:
            return None  # engine failure (None = fault; "" = no relation)
