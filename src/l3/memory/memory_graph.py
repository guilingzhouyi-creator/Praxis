"""MemoryGraph — R5 swarm-domain graph layer: semantic topology index over R1-R4.

Layered architecture:
  R1-R3  Operational memory (agent runtime fast access)
  R4     Lossless archive (full, rollback-capable, audit baseline)
  R5     Swarm-domain graph (this module) — semantic topology index of the archive:
           Nodes = MemEntry per ring (natural nodes: id/type/tags/importance)
           Edges = Rule-based edges (sequential / type_chain / cell_chain)
           Retrieval = Diffusion activation (seed traversal along edges)
           Reduction = Graph reduction (degree centrality: keep hubs, prune leaves)

Module layout (split for readability):
  memory_graph_constants.py — relation vocabulary + edge-mode state machine
  memory_graph_semantic.py  — SemanticExtractionMixin (hybrid LLM edges)
  memory_graph.py            — MemoryGraph core (storage / rule edges / recall /
                               compact / semantic edges / stats) + singleton

Governance semantics:
  - Toggle: enabled (default false — reads settings ``memory.graph.enabled``)
  - Attribution: each edge records created_by (who built the edge)
  - Derivation: graph can be rebuilt from R4 (errors do not affect the archive, which is ground truth)
  - Isolation: each MemoryManager instance holds an independent graph (scope isolation)

Storage: SQLite ``memory_edges`` table (separate database, separated from knowledge table).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .memory_graph_constants import (  # noqa: F401 — re-export
    _COMPACT_MIN_EDGES,
    _DEFAULT_DB_NAME,
    _DEFAULT_ENABLED,
    _EDGE_ID_LEN,
    _EDGE_MODE_HYBRID,
    _EDGE_MODE_OFF,
    _EDGE_MODE_PAUSED,
    _EDGE_MODE_RULES,
    _EDGE_MODE_TRANSITIONS,
    _EDGE_MODES,
    _LLM_EXTRACT_MAX_PAIRS,
    _LLM_EXTRACT_MAX_TOKENS,
    _REL_CELL_CHAIN,
    _REL_CONTRADICTS,
    _REL_DEPENDS_ON,
    _REL_EVIDENCE,
    _REL_REFINES,
    _REL_SEQUENTIAL,
    _REL_TYPE_CHAIN,
    _SEMANTIC_RELATIONS,
    _default_enabled,
)
from .memory_graph_semantic import SemanticExtractionMixin  # noqa: F401 — re-export

logger = logging.getLogger(__name__)


class MemoryGraph(SemanticExtractionMixin):
    """Semantic graph engine: edge table management, rule-based edge building, diffusion retrieval, graph reduction."""

    def __init__(self, db_path: str = "", enabled: bool | None = None):
        self._enabled = _default_enabled() if enabled is None else enabled
        self._edge_mode = self._default_edge_mode()
        self._lock = threading.RLock()
        if db_path:
            self._db_path = db_path
        else:
            from l1.kernel.paths import get_paths

            self._db_path = str(Path(get_paths().data_dir) / _DEFAULT_DB_NAME)
        self._conn: sqlite3.Connection | None = None
        self._connect()

    def _default_edge_mode(self) -> str:
        try:
            from l1.kernel.settings import get_settings

            m = str(get_settings().get("memory.graph.edge_mode", _EDGE_MODE_OFF))
            return m if m in _EDGE_MODES else _EDGE_MODE_OFF
        except Exception:
            return _EDGE_MODE_OFF

    # ── Storage ────────────────────────────────────────────────

    def _connect(self) -> None:
        try:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_edges (
                    id         TEXT PRIMARY KEY,
                    from_id    TEXT NOT NULL,
                    to_id      TEXT NOT NULL,
                    relation   TEXT NOT NULL,
                    weight     REAL DEFAULT 1.0,
                    created_by TEXT NOT NULL DEFAULT 'system',
                    created_at REAL NOT NULL
                )
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_from ON memory_edges(from_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_to ON memory_edges(to_id)")
            self._conn.commit()
        except Exception as e:
            logger.warning("memory_graph: connect failed: %s", e)
            self._conn = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, flag: bool) -> None:
        """Enable or disable the memory graph, emitting a switch event."""
        changed = self._enabled != bool(flag)
        self._enabled = bool(flag)
        logger.info("memory_graph: enabled=%s", self._enabled)
        if changed:
            self._emit_event("stats.memory.graph.switch", {"enabled": self._enabled})

    # ── Semantic extraction state machine ─────────────────────────────────────

    @property
    def edge_mode(self) -> str:
        return self._edge_mode

    def set_edge_mode(self, mode: str) -> dict:
        """Transition the semantic-extraction state machine.

        off → rules → hybrid ⇄ paused
        Invalid transitions are rejected (governance: no arbitrary jumps).
        """
        mode = str(mode).strip().lower()
        if mode not in _EDGE_MODES:
            return {"success": False, "error": f"edge_mode must be one of {list(_EDGE_MODES)}"}
        if mode == self._edge_mode:
            return {"success": True, "edge_mode": mode, "changed": False}
        allowed = _EDGE_MODE_TRANSITIONS.get(self._edge_mode, set())
        if mode not in allowed:
            return {
                "success": False,
                "error": f"invalid transition: {self._edge_mode} -> {mode} (allowed: {sorted(allowed)})",
            }
        old = self._edge_mode
        self._edge_mode = mode
        logger.info("memory_graph: edge_mode %s -> %s", old, mode)
        self._emit_event(
            "stats.memory.graph.edge_mode",
            {
                "from": old,
                "to": mode,
            },
        )
        return {"success": True, "edge_mode": mode, "changed": True, "from": old}

    def _emit_event(self, event_type: str, data: dict) -> None:
        """Publish graph lifecycle events to the monitoring bus + StatsCenter."""
        try:
            from l3.bus.monitor_bus import MonitorEvent as _MEv
            from l3.bus.monitor_bus import get_bus as _MB

            _MB().emit(_MEv(type=event_type, source="memory_graph", severity="info", data=data))
        except Exception:
            logger.debug("memory_graph: monitor emit failed")
        # Phase F: memory-graph lifecycle events also land in StatsCenter so
        # RC time series cover the R5 graph (compact/edge_mode/semantic/switch).
        try:
            from l3.services.stats_center import MetricPoint, get_center

            get_center().ingest(
                MetricPoint(
                    name=event_type,
                    value=1.0,
                    tags={"source": "memory_graph"},
                    timestamp=time.time(),
                    metric_type="counter",
                )
            )
        except Exception:
            logger.debug("memory_graph: stats ingest failed")

    # ── Rule-based edges (zero cost, no LLM) ────────────────────────────

    def remember_hook(
        self,
        entry_id: str,
        agent_id: str,
        entry_type: str,
        cell_id: str,
        recent: list[dict],
        created_by: str = "system",
    ) -> list[str]:
        """Called after remember(): build rule-based edges to recent entries.

        Args:
            recent: list of {"id", "entry_type", "agent_id", "cell_id"} for
                    the most recent entries (provided by MemoryManager).
        Returns: list of created edge ids (empty when disabled).
        """
        if not self._enabled or self._conn is None:
            return []
        created: list[str] = []
        now = time.time()
        try:
            with self._lock:
                for r in recent:
                    if not r or r.get("id") == entry_id:
                        continue  # never self-loop
                    rel = ""
                    w = 1.0
                    if r.get("agent_id") == agent_id:
                        rel = _REL_SEQUENTIAL
                        w = 1.0
                        if entry_type and r.get("entry_type") == entry_type:
                            rel = _REL_TYPE_CHAIN  # same-agent + same type = strongest
                            w = 1.2
                    elif r.get("cell_id") and r.get("cell_id") == cell_id:
                        rel = _REL_CELL_CHAIN
                        w = 0.8
                    if not rel:
                        continue
                    if self._edge_exists(r["id"], entry_id, rel):
                        continue
                    eid = self._insert_edge(
                        from_id=r["id"], to_id=entry_id, relation=rel, weight=w, created_by=created_by, created_at=now
                    )
                    if eid:
                        created.append(eid)
        except Exception as e:
            logger.debug("memory_graph: remember_hook failed: %s", e)
        return created

    def _edge_exists(self, from_id: str, to_id: str, relation: str) -> bool:
        if self._conn is None:
            return False
        cur = self._conn.execute(
            "SELECT 1 FROM memory_edges WHERE from_id=? AND to_id=? AND relation=? LIMIT 1", (from_id, to_id, relation)
        )
        return cur.fetchone() is not None

    def _insert_edge(
        self, from_id: str, to_id: str, relation: str, weight: float, created_by: str, created_at: float
    ) -> str | None:
        if self._conn is None:
            return None
        eid = f"edge-{uuid.uuid4().hex[:_EDGE_ID_LEN]}"
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO memory_edges "
                "(id, from_id, to_id, relation, weight, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (eid, from_id, to_id, relation, weight, created_by, created_at),
            )
            self._conn.commit()
            return eid
        except Exception as e:
            logger.debug("memory_graph: insert failed: %s", e)
            return None

    def add_evidence_edge(self, from_id: str, to_id: str, weight: float = 1.0, created_by: str = "evidence") -> dict:
        """Add an ``evidence`` edge between two entries (B6 evidence→R5 linkage).

        Uses the reserved semantic relation slot (docs/notes/roadmap-
        research-generalization.md §6.1) without touching the existing
        contradicts/depends_on/refines semantics. Graceful when the graph
        is disabled (returns success=False with a note, never raises).
        """
        if not self._enabled or self._conn is None:
            return {"success": False, "note": "memory graph disabled"}
        if self._edge_exists(from_id, to_id, _REL_EVIDENCE):
            return {"success": True, "edge_id": "", "duplicate": True}
        eid = self._insert_edge(
            from_id, to_id, _REL_EVIDENCE, weight=weight, created_by=created_by, created_at=time.time()
        )
        return {"success": eid is not None, "edge_id": eid or ""}

    # ── Diffusion retrieval (seed traversal along edges) ──────────────────────────────

    def recall(self, seeds: list[str], depth: int = 2, limit: int = 20) -> dict:
        """Diffusion retrieval: BFS from seed entries.

        Returns:
            {"nodes": [entry_id...], "edges": [{from_id, to_id, relation, weight}],
             "stats": {"seeds": N, "depth": D, "reached": N}}
        """
        if not self._enabled or self._conn is None:
            return {"nodes": [], "edges": [], "stats": {"seeds": len(seeds), "depth": 0, "reached": 0}}
        reached: dict[str, int] = {}
        frontier: list[str] = [s for s in seeds if s]
        for d in range(max(1, depth)):
            nxt: list[str] = []
            for fid in frontier:
                if fid in reached:
                    continue
                reached[fid] = d + 1
                try:
                    cur = self._conn.execute(
                        "SELECT to_id FROM memory_edges WHERE from_id=? "
                        "UNION SELECT from_id FROM memory_edges WHERE to_id=?",
                        (fid, fid),
                    )
                    for row in cur.fetchall():
                        nxt.append(row[0])
                except Exception:
                    break
            if not nxt:
                break
            frontier = nxt
        nodes = list(reached.keys())[:limit]
        edges: list[dict] = []
        try:
            cur = self._conn.execute(
                "SELECT from_id, to_id, relation, weight FROM memory_edges "
                "WHERE from_id IN ({ph}) OR to_id IN ({ph}) LIMIT {lim}".format(
                    ph=",".join("?" * len(nodes)), lim=limit * 2
                ),
                list(nodes) + list(nodes),
            )
            for fid, tid, rel, w in cur.fetchall():
                edges.append({"from_id": fid, "to_id": tid, "relation": rel, "weight": w})
        except Exception:
            logger.debug("memory_graph: edge query failed, returning empty edges", exc_info=True)
        return {"nodes": nodes, "edges": edges, "stats": {"seeds": len(seeds), "depth": depth, "reached": len(nodes)}}

    # ── Graph reduction (degree centrality analysis + executable pruning) ──────────────────

    def compact_report(self, min_degree: int = 2) -> dict:
        """Graph reduction analysis: keep hubs, prune leaves.

        Returns (read-only analysis — actual pruning is a policy decision):
            {"hubs": [{"entry_id", "degree"}], "leaves": N, "edges": N}
        """
        if self._conn is None:
            return {"hubs": [], "leaves": 0, "edges": 0}
        try:
            cur = self._conn.execute(
                "SELECT entry, COUNT(*) AS deg FROM ("
                "  SELECT from_id AS entry FROM memory_edges "
                "  UNION ALL SELECT to_id AS entry FROM memory_edges"
                ") GROUP BY entry"
            )
            degrees = {row[0]: row[1] for row in cur.fetchall()}
            hubs = [{"entry_id": eid, "degree": deg} for eid, deg in degrees.items() if deg >= min_degree]
            leaves = sum(1 for deg in degrees.values() if deg == 1)
            total_edges = self._conn.execute("SELECT COUNT(*) FROM memory_edges").fetchone()[0]
            return {"hubs": hubs, "leaves": leaves, "edges": total_edges}
        except Exception as e:
            logger.debug("memory_graph: compact_report failed: %s", e)
            return {"hubs": [], "leaves": 0, "edges": 0}

    def compact(self, min_degree: int = 2, dry_run: bool = True) -> dict:
        """Graph reduction (executable): prune leaves, keep hubs.

        Leaves (degree == 1) are the low-connectivity noise — pruning them
        shrinks the topology while hub nodes survive. The graph is a derived
        layer: it can be rebuilt from R4 archives, so pruning is recoverable.

        Args:
            min_degree: hub threshold (degree >= min_degree survives)
            dry_run: True → report only; False → actually delete leaf edges
        """
        if self._conn is None:
            return {"success": False, "error": "no connection"}
        rep = self.compact_report(min_degree=min_degree)
        if not dry_run and rep["edges"] < _COMPACT_MIN_EDGES:
            return {
                "success": False,
                "dry_run": False,
                "error": f"graph too small for pruning ({rep['edges']} < {_COMPACT_MIN_EDGES})",
                "edges_before": rep["edges"],
                "edges_after": rep["edges"],
            }
        # Leaves = degree-1 nodes (low-connectivity noise)
        try:
            cur = self._conn.execute(
                "SELECT entry, COUNT(*) AS deg FROM ("
                "  SELECT from_id AS entry FROM memory_edges "
                "  UNION ALL SELECT to_id AS entry FROM memory_edges"
                ") GROUP BY entry HAVING deg = 1"
            )
            leaf_ids = [row[0] for row in cur.fetchall()]
        except Exception:
            leaf_ids = []
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "leaves": len(leaf_ids),
                "edges_before": rep["edges"],
                "edges_after": rep["edges"],
            }
        removed = 0
        try:
            with self._lock:
                for eid in leaf_ids:
                    cur = self._conn.execute("DELETE FROM memory_edges WHERE from_id=? OR to_id=?", (eid, eid))
                    removed += cur.rowcount
                self._conn.commit()
        except Exception as e:
            logger.debug("memory_graph: compact failed: %s", e)
            return {"success": False, "error": str(e)}
        after = self._conn.execute("SELECT COUNT(*) FROM memory_edges").fetchone()[0]
        self._emit_event(
            "stats.memory.graph.compact",
            {
                "leaves_pruned": len(leaf_ids),
                "edges_removed": removed,
                "edges_before": rep["edges"],
                "edges_after": after,
            },
        )
        return {
            "success": True,
            "dry_run": False,
            "leaves_pruned": len(leaf_ids),
            "edges_removed": removed,
            "edges_before": rep["edges"],
            "edges_after": after,
            "hubs_kept": len(rep["hubs"]),
        }

    # ── Semantic edges (explicit writes — contradicts/depends_on/refines) ────────

    def add_semantic_edge(
        self, from_id: str, to_id: str, relation: str, weight: float = 1.5, created_by: str = "llm"
    ) -> dict:
        """Add a semantic edge (contradicts/depends_on/refines).

        Unlike rule-based edges (automatic, zero cost), semantic edges are
        explicit knowledge: callers (LLM extraction, review passes, humans)
        decide the relation and attribution is recorded.

        Returns: {"success": True, "edge_id": ...} or error dict.
        """
        if self._conn is None:
            return {"success": False, "error": "no connection"}
        if not self._enabled:
            return {"success": False, "error": "graph disabled"}
        rel = relation.strip().lower()
        if rel not in _SEMANTIC_RELATIONS:
            return {"success": False, "error": f"relation must be one of {sorted(_SEMANTIC_RELATIONS)}"}
        if not from_id or not to_id or from_id == to_id:
            return {"success": False, "error": "from_id/to_id required and distinct"}
        if self._edge_exists(from_id, to_id, rel):
            return {"success": False, "error": "edge already exists"}
        try:
            eid = self._insert_edge(from_id, to_id, rel, float(weight), created_by, time.time())
            if not eid:
                return {"success": False, "error": "insert failed"}
            self._emit_event(
                "stats.memory.graph.semantic",
                {
                    "relation": rel,
                    "from_id": from_id,
                    "to_id": to_id,
                    "created_by": created_by,
                },
            )
            return {"success": True, "edge_id": eid, "relation": rel}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def semantic_edges(self, limit: int = 50) -> list[dict]:
        """List semantic edges only (contradicts/depends_on/refines)."""
        if self._conn is None:
            return []
        try:
            ph = ",".join("?" * len(_SEMANTIC_RELATIONS))
            cur = self._conn.execute(
                "SELECT from_id, to_id, relation, weight, created_by, created_at "
                f"FROM memory_edges WHERE relation IN ({ph}) "
                "ORDER BY created_at DESC LIMIT ?",
                list(_SEMANTIC_RELATIONS) + [limit],
            )
            return [
                {
                    "from_id": r[0],
                    "to_id": r[1],
                    "relation": r[2],
                    "weight": r[3],
                    "created_by": r[4],
                    "created_at": r[5],
                }
                for r in cur.fetchall()
            ]
        except Exception:
            return []

    # ── Query / Maintenance ─────────────────────────────────────────

    def edges_of(self, entry_id: str, limit: int = 20) -> list[dict]:
        """Return edges touching the given entry id, both directions."""
        if self._conn is None:
            return []
        try:
            cur = self._conn.execute(
                "SELECT from_id, to_id, relation, weight, created_by, created_at "
                "FROM memory_edges WHERE from_id=? OR to_id=? LIMIT ?",
                (entry_id, entry_id, limit),
            )
            return [
                {
                    "from_id": r[0],
                    "to_id": r[1],
                    "relation": r[2],
                    "weight": r[3],
                    "created_by": r[4],
                    "created_at": r[5],
                }
                for r in cur.fetchall()
            ]
        except Exception:
            return []

    def stats(self) -> dict:
        """Return graph statistics: enabled flag, edge count, and DB path."""
        if self._conn is None:
            return {"enabled": self._enabled, "edges": 0, "db": self._db_path}
        try:
            total = self._conn.execute("SELECT COUNT(*) FROM memory_edges").fetchone()[0]
            by_rel: dict[str, int] = {}
            for row in self._conn.execute("SELECT relation, COUNT(*) FROM memory_edges GROUP BY relation"):
                by_rel[row[0]] = row[1]
            return {"enabled": self._enabled, "edges": total, "by_relation": by_rel, "db": self._db_path}
        except Exception:
            return {"enabled": self._enabled, "edges": 0, "db": self._db_path}

    def clear(self) -> int:
        """Delete all graph edges; returns the number of removed rows."""
        if self._conn is None:
            return 0
        try:
            with self._lock:
                n = self._conn.execute("DELETE FROM memory_edges").rowcount
                self._conn.commit()
                return n
        except Exception:
            return 0

    def close(self) -> None:
        """Close the underlying SQLite connection, if open."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                logger.debug("memory_graph: connection close failed, ignored", exc_info=True)
            self._conn = None


# ── Module-level singleton (conftest-resettable) ─────────────

_graph: MemoryGraph | None = None
_graph_lock = threading.Lock()


def get_graph(db_path: str = "") -> MemoryGraph:
    """Get the singleton MemoryGraph, creating it with the given DB path."""
    global _graph
    if _graph is None:
        with _graph_lock:
            if _graph is None:
                _graph = MemoryGraph(db_path=db_path)
    return _graph


def reset_graph() -> None:
    """Close and reset the singleton MemoryGraph (for testing)."""
    global _graph
    with _graph_lock:
        if _graph is not None:
            try:
                _graph.close()
            except Exception:
                logger.debug("memory_graph: singleton close failed, ignored", exc_info=True)
            _graph = None
