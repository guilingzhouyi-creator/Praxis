"""MemoryGraph — R5 graph constants and edge-mode state machine.

Extracted from ``memory_graph.py``: the edge relation vocabulary, the
semantic-extraction state machine (off / rules / hybrid / paused) and the
module defaults shared by the graph engine and its semantic mixin.
"""

from __future__ import annotations

_EDGE_ID_LEN = 12

_REL_SEQUENTIAL = "sequential"  # same-agent sequential write chain
_REL_TYPE_CHAIN = "type_chain"  # same-agent + same entry_type chain
_REL_CELL_CHAIN = "cell_chain"  # same-cell chain

# ── Semantic edges (hybrid mode — explicitly written by caller/LLM) ──
_REL_CONTRADICTS = "contradicts"  # new knowledge overrides old knowledge
_REL_DEPENDS_ON = "depends_on"  # decision dependency basis
_REL_REFINES = "refines"  # refine / supplement
_REL_EVIDENCE = "evidence"  # evidence-chain linkage (B6: security/evidence → R5)

_SEMANTIC_RELATIONS = {_REL_CONTRADICTS, _REL_DEPENDS_ON, _REL_REFINES, _REL_EVIDENCE}

# ── Semantic extraction state machine (governance toggle for LLM auto-semantic edges) ──
#   off    → no extraction (default, rule-based only)
#   rules  → rule-based edges only (semantic extraction disabled)
#   hybrid → rule-based edges + LLM semantic edges (auto-extraction during reduction)
#   paused → semantic extraction paused (auto-downgraded on LLM failure / cost overrun)
_EDGE_MODE_OFF = "off"
_EDGE_MODE_RULES = "rules"
_EDGE_MODE_HYBRID = "hybrid"
_EDGE_MODE_PAUSED = "paused"
_EDGE_MODES = (_EDGE_MODE_OFF, _EDGE_MODE_RULES, _EDGE_MODE_HYBRID, _EDGE_MODE_PAUSED)
_EDGE_MODE_TRANSITIONS: dict[str, set[str]] = {
    _EDGE_MODE_OFF: {_EDGE_MODE_RULES, _EDGE_MODE_HYBRID},
    _EDGE_MODE_RULES: {_EDGE_MODE_OFF, _EDGE_MODE_HYBRID},
    _EDGE_MODE_HYBRID: {_EDGE_MODE_OFF, _EDGE_MODE_RULES, _EDGE_MODE_PAUSED},
    _EDGE_MODE_PAUSED: {_EDGE_MODE_OFF, _EDGE_MODE_RULES, _EDGE_MODE_HYBRID},
}
_LLM_EXTRACT_MAX_PAIRS = 5  # max comparison pairs per extraction round
_LLM_EXTRACT_MAX_TOKENS = 256
_LLM_EXTRACT_MAX_WORKERS = 4  # concurrent LLM calls for pair relations during extraction

_DEFAULT_DB_NAME = "memory_graph.db"
_DEFAULT_ENABLED = False
_COMPACT_MIN_EDGES = (
    4  # skip pruning when graph has fewer edges than this (prevent newborn graph from being pruned empty)
)


def _default_enabled() -> bool:
    """Read the global switch from settings (memory.graph.enabled)."""
    try:
        from l1.kernel.settings import get_settings

        return bool(get_settings().get("memory.graph.enabled", _DEFAULT_ENABLED))
    except Exception:
        return _DEFAULT_ENABLED
