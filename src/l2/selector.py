"""Selector — identity selection + pre-connect verification for Direct Mode.

Flow:
  1. PreSelector: scan all Cells → collect agent rosters (PID, role, status)
  2. Selector: route by agent_id / role / territory → (cell_id, agent_id)
  3. PreConnect: verify liveness + prompt injection check → allow/deny

TS rewrite reference: the selector consumes the bridge's dict data API
(cell_ids / cell_liveness / cell_agent_reachable / cell_territory) so no
L3 cell object handle ever leaks into L2; the TS side mirrors this as a
local projection fed by the same bridge calls — selection logic stays in
Python, TS only renders the outcome.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from l1.kernel.params.system import TLB_DEFAULT_RING
from l2.bridge import capture
from l2.i18n import t as _t

logger = logging.getLogger(__name__)

# ── Role-based reverse index: role → [(cell_id, agent_id)]
# Built by preselect(), consumed by _select_best() for O(1) role lookup.
_role_index: dict[str, list[tuple[str, str]]] = {}
_role_index_stale: bool = True
_role_index_lock = threading.Lock()

# Injection policy (patterns, thresholds, reviewer) lives in L3:
# l3.services.injection_guard — reached via l2.bridge.injection_verify.

# ── Agent identity ──


@dataclass
class AgentIdentity:
    """Identifies a Peer Agent across Cells."""

    cell_id: str = ""
    agent_id: str = ""
    role: str = ""
    pid: int = 0
    ring: int = TLB_DEFAULT_RING
    territory: list[str] = field(default_factory=list)
    status: str = ""
    reachable: bool = False


# ── PreSelector: scan all Cells ──


def preselect() -> dict:
    """Scan all registered Cells, collect agent rosters with status.

    Returns:
        {"agents": [AgentIdentity, ...], "cells": [cell_id, ...], "total": int}
    """
    agents: list[dict] = []
    cell_ids: list[str] = []

    try:
        from l2.bridge import cell_ids as list_cell_ids
        from l2.bridge import cell_liveness

        cell_id_list = list_cell_ids()
    except Exception as e:
        logger.warning("preselect: get_cells failed: %s", e)
        return {"agents": [], "cells": [], "total": 0, "error": _t("shell.app_error.cell_service_unavailable")}

    for cell_id in cell_id_list:
        cell_ids.append(cell_id)
        try:
            liveness = cell_liveness(cell_id)
            for aid, ainfo in liveness.get("agents", {}).items():
                agents.append(
                    {
                        "cell_id": cell_id,
                        "agent_id": aid,
                        "role": ainfo.get("role", ainfo.get("status", "?")),
                        "status": ainfo.get("status", "unknown"),
                        "alive": ainfo.get("alive", False),
                        "territory": liveness.get("territory", []),
                    }
                )
        except Exception as e:
            logger.warning("preselect cell %s: %s", cell_id, e)
            capture("preselect cell failed", error_code="E_PRESELECT", component="l2", context={"cell_id": cell_id})

    # Build role index for O(1) subsequent lookups
    if agents:
        _rebuild_role_index(cell_ids)

    return {"agents": agents, "cells": cell_ids, "total": len(agents)}


def _rebuild_role_index(cell_id_list: list[str]) -> None:
    """Build reverse index: role → [(cell_id, agent_id)] for O(1) lookup."""
    from l2.bridge import cell_liveness

    global _role_index, _role_index_stale
    idx: dict[str, list[tuple[str, str]]] = {}
    for cell_id in cell_id_list:
        try:
            liveness = cell_liveness(cell_id)
            for aid, ainfo in liveness.get("agents", {}).items():
                role = ainfo.get("role", ainfo.get("status", "?")).lower()
                idx.setdefault(role, []).append((cell_id, aid))
        except Exception as e:
            logger.warning("preselect cell %s: %s", cell_id, e)
            capture(
                "preselect cell role_index failed",
                error_code="E_PRESELECT",
                component="l2",
                context={"cell_id": cell_id},
            )
            continue
    with _role_index_lock:
        _role_index = idx
        _role_index_stale = False


# ── Selector: route to specific agent ──


def select(cell_id: str = "", agent_id: str = "", role: str = "", domain: str = "") -> dict:
    """Select a specific agent by cell_id + agent_id, or by role/domain.

    Returns:
        {"success": bool, "cell_id": str, "agent_id": str,
         "identity": AgentIdentity, "error": str}
    """
    if agent_id:
        return _select_by_id(agent_id)

    if cell_id:
        return _select_by_role(cell_id, role, domain)

    # Scan all cells for best match
    result = _select_best(role, domain)
    if result.get("success"):
        return result

    return {"success": False, "error": _t("shell.app_error.no_matching_agent")}


# ── PreConnect verification ──


def preconnect(cell_id: str, agent_id: str, message: str = "") -> dict:
    """Verify connection is healthy and message is safe before routing.

    Checks:
      1. Cell liveness
      2. Agent reachability
      3. Prompt injection (if message provided)

    Returns:
        {"allowed": bool, "reason": str, "injection_risk": float}
    """
    reasons = []
    injection_risk = 0.0

    # 1. Cell liveness
    try:
        from l2.bridge import cell_agent_reachable, cell_liveness

        liveness = cell_liveness(cell_id)
        if liveness.get("overall") == "unreachable":
            return {"allowed": False, "reason": "cell_unreachable", "injection_risk": 0.0}
    except Exception as e:
        return {"allowed": False, "reason": f"cell_error: {e}", "injection_risk": 0.0}

    # 2. Agent reachability
    try:
        reachable = cell_agent_reachable(cell_id, agent_id)
        if not reachable.get("reachable"):
            reasons.append(reachable.get("reason", "unreachable"))
    except Exception as e:
        reasons.append(f"agent_check: {e}")

    # 3. Prompt injection scan (policy lives in L3 injection_guard)
    if message:
        from l2.bridge import injection_verify

        verdict = injection_verify(message)
        if not verdict["allowed"]:
            reasons.append(verdict["reason"])
        injection_risk = verdict["injection_risk"]

    return {
        "allowed": len(reasons) == 0,
        "reason": "; ".join(reasons) if reasons else "ok",
        "injection_risk": round(injection_risk, 2),
    }


# ── Internal ──


def _select_by_id(agent_id: str) -> dict:
    """Find an agent by ID across all Cells.  Returns {"success", "cell_id", "agent_id"}."""
    from l2.bridge import cell_agent_reachable
    from l2.bridge import cell_ids as list_cell_ids

    for cell_id in list_cell_ids():
        try:
            r = cell_agent_reachable(cell_id, agent_id)
            if r.get("reachable"):
                return {
                    "success": True,
                    "cell_id": cell_id,
                    "agent_id": agent_id,
                }
        except Exception as e:
            logger.warning("select_by_id %s/%s: %s", cell_id, agent_id, e)
            capture(
                "select_by_id failed",
                error_code="E_SELECT",
                component="l2",
                context={"cell_id": cell_id, "agent_id": agent_id},
            )
            continue
    return {"success": False, "error": _t("shell.app_error.agent_unreachable", agent_id=agent_id)}


def _select_by_role(cell_id: str, role: str, domain: str) -> dict:
    from l2.bridge import cell_liveness

    try:
        liveness = cell_liveness(cell_id)
        for aid, info in liveness.get("agents", {}).items():
            if info.get("role", info.get("status", "")).lower() == role.lower():
                return {"success": True, "cell_id": cell_id, "agent_id": aid}
    except Exception as e:
        logger.warning("select_by_role %s/%s: %s", cell_id, role, e)
        capture(
            "select_by_role failed", error_code="E_SELECT", component="l2", context={"cell_id": cell_id, "role": role}
        )
    return {"success": False, "error": _t("shell.app_error.no_agent_with_role", role=role, cell_id=cell_id)}


def _select_best(role: str, domain: str) -> dict:
    global _role_index, _role_index_stale
    from l2.bridge import cell_ids as list_cell_ids
    from l2.bridge import cell_liveness, cell_territory

    best = None
    best_score = -1

    # Use role index for O(1) initial candidate selection
    if role:
        role_lower = role.lower()
        with _role_index_lock:
            stale = _role_index_stale
            candidates = _role_index.get(role_lower, []) if not stale else []
        if stale:
            try:
                _rebuild_role_index(list_cell_ids())
            except Exception as e:
                logger.warning("_rebuild_role_index failed: %s", e)
                capture("_rebuild_role_index failed", error_code="E_PRESELECT", component="l2")
            with _role_index_lock:
                candidates = _role_index.get(role_lower, [])
    else:
        candidates = []

    if not candidates:
        # Fallback: scan all cells × agents (O(C×A))
        for cell_id in list_cell_ids():
            lv = cell_liveness(cell_id)
            agents_data = lv.get("agents", {})
            territory_roots = cell_territory(cell_id)
            for aid, info_dict in agents_data.items():
                score = 0
                info_role = info_dict.get("role", "")
                if role and info_role.lower() == role.lower():
                    score += 2
                if domain:
                    for t in territory_roots:
                        if domain.startswith(t):
                            score += 1
                if score > best_score:
                    best_score = score
                    best = (cell_id, aid)
    else:
        # Index hit: only score candidates matching the role.
        # Cache key is the cell id; the local value name must never shadow
        # the ``cell_territory`` bridge function imported above (a previous
        # shadowing bug silently zeroed territory scoring for the 2nd+ cell).
        territory_cache: dict[str, list[str]] = {}
        for cell_id, aid in candidates:
            if cell_id not in territory_cache:
                try:
                    territory_cache[cell_id] = cell_territory(cell_id)
                except Exception as e:
                    logger.warning("territory cache for %s: %s", cell_id, e)
                    capture(
                        "cell territory cache failed",
                        error_code="E_CACHE",
                        component="l2",
                        context={"cell_id": cell_id},
                    )
                    territory_cache[cell_id] = []
            score = 2  # role match
            if domain:
                for t in territory_cache[cell_id]:
                    if domain.startswith(t):
                        score += 1
            if score > best_score:
                best_score = score
                best = (cell_id, aid)

    if best:
        return {"success": True, "cell_id": best[0], "agent_id": best[1]}
    return {"success": False, "error": _t("shell.app_error.no_matching_agent")}
