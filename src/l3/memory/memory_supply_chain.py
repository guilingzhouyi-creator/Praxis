"""Memory supply chain (Phase 3, M3) — feed purified memory to consumers.

Consumes the MemoryRefinery output (M2 records) and supplies it to:

  supply_to_r5        — R5 graph modeling (semantic edges)
  re_inject_filtered  — re-injection with identity/Cell-domain filtering
  supply_to_skills    — generalized skill evolution input (R4Agent)
  agent_md_active     — per-Cell Agent handbook, activated at 2+ Cells

Every consumer degrades gracefully (never raises): a disabled consumer or
an unavailable dependency returns an empty/False result.
"""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel.params.agent import CELL_DEPARTMENT_MIN
from l1.kernel.params.system import MEMORY_REFINERY_SUPPLY_SKILLS_DEFAULT

logger = logging.getLogger(__name__)


def supply_after_refine(records: list[dict[str, Any]]) -> dict:
    """Feed refined records to downstream consumers (M3 orchestrator).

    Called by the refinery write-path hook after records are persisted:
    R5 graph edges (graph-gated internally) and the generalized skill
    system (gated by the operator switch ``MEMORY_REFINERY_SUPPLY_SKILLS_DEFAULT``
    — LLM skill evolution is heavy and stays off unless enabled).

    Degrades gracefully: every consumer returns 0 / False on failure.

    Returns:
        ``{"r5_edges": N, "skills_supplied": N, "agent_md_active": bool}``.
    """
    r5 = supply_to_r5(records)
    skills = supply_to_skills(records) if MEMORY_REFINERY_SUPPLY_SKILLS_DEFAULT else 0
    return {"r5_edges": r5, "skills_supplied": skills, "agent_md_active": agent_md_active()}


def supply_to_r5(records: list[dict[str, Any]], created_by: str = "memory_refinery") -> int:
    """Feed refined records into the R5 graph (semantic edges, non-blocking).

    Args:
        records: Transformed records from MemoryRefinery.transform.
        created_by: Attribution for the graph edges.

    Returns:
        Number of edges created (0 when the graph is disabled/unavailable).
    """
    created = 0
    try:
        from l3.memory.memory_graph import get_graph

        g = get_graph()
        if not g.enabled:
            return 0
        for rec in records:
            if not rec.get("entry_id"):
                continue
            g.add_semantic_edge(
                rec["entry_id"],
                rec.get("entry_type", "note"),
                weight=float(rec.get("refinery_score", 0.0) or 1.0),
                created_by=created_by,
            )
            created += 1
    except Exception as e:
        logger.debug("memory_supply_chain: R5 supply skipped: %s", e)
    return created


def re_inject_filtered(
    entries: list[dict[str, Any]],
    cell_id: str = "",
    role: str = "",
    scope: str = "",
    intent: str = "",
    domain: str = "",
) -> list[dict[str, Any]]:
    """Re-injection with identity/Cell-domain filtering (M1 gate applied).

    Wraps retrieval so only domain-allowed entries re-enter the context.
    ``intent``/``domain`` carry the driving card's identity-hit (HTN-C
    match) so the fine-grained identity gate follows task dispatch instead
    of falling back to the static binding set.
    Disabled filter → entries pass through unchanged.
    """
    try:
        from l3.memory.memory_domain_filter import get_memory_filter

        return get_memory_filter().filter_entries(
            entries, cell_id=cell_id, role=role, scope=scope, intent=intent, domain=domain
        )
    except Exception as e:
        logger.debug("memory_supply_chain: re-inject filter skipped: %s", e)
        return entries


def supply_to_skills(records: list[dict[str, Any]]) -> int:
    """Submit refined records to the R4 candidate ledger.

    The legacy function name remains for callers, but refined records no
    longer publish an evolved skill directly. They first accumulate in the
    candidate ledger, where evidence validation and controlled publication
    decide whether R4Agent may generate a skill. Returns the count accepted
    by the ledger.

    Args:
        records: Transformed records from MemoryRefinery.transform.

    Returns:
        Number of records accepted by the candidate ledger.
    """
    supplied = 0
    try:
        from l3.memory.r4_candidate_store import get_candidate_store

        accepted = get_candidate_store().submit_records(records, source="refined_memory")
        supplied = int(accepted.get("submitted", 0) or 0)
    except Exception as e:
        logger.debug("memory_supply_chain: candidate supply skipped: %s", e)
    return supplied


def agent_md_active(cell_count: int | None = None) -> bool:
    """Whether per-Cell Agent handbooks are active (2+ Cells, M3).

    Before the department threshold every Cell shares the global handbook;
    at CELL_DEPARTMENT_MIN+ the per-Cell Agent.md activates (model-visible,
    carrying the cell's prior-work program).
    """
    try:
        if cell_count is None:
            from l3.cell import get_cells

            cell_count = len(get_cells())
        return cell_count >= CELL_DEPARTMENT_MIN
    except Exception as e:
        logger.debug("memory_supply_chain: agent_md_active failed: %s", e)
        return False
