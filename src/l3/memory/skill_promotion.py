"""Skill promotion transaction + canary automation (3.x, P1.3 / P1.4).

**P1.3 — promotion transaction.** Promoting an evolved candidate spans two
writers: the candidate ledger (``CandidateStore.transition``) and the skill
library (``SkillManager.register``). This module wraps them in a journaled,
compensating transaction:

    1. intent   — journal ``{phase: "begin", ...}``
    2. library  — register/update the skill via SkillManager
    3. ledger   — mark the candidate promoted (``transition``)
    4. commit   — journal ``{phase: "done"}``; idempotent on replay

Compensation: a failure AFTER step 2 restores the pre-transaction skill
record (or deletes a freshly created one). A failure after step 3 is
reported honestly — never silently treated as success.

**P1.4 — canary automation.** A promoted skill observed below threshold
(success rate / trials / optional latency) is auto-quarantined: archived,
marked deprecated, and tagged — with the evidence recorded.

TS-mirror note: every persisted shape here is a plain JSON map with a
documented field list; no Python-only objects cross the boundary.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from l1.kernel.params.system import (
    SKILL_CANARY_MAX_LATENCY_MS,
    SKILL_CANARY_MIN_SUCCESS_RATE,
    SKILL_CANARY_MIN_TRIALS,
    SKILL_CANARY_QUARANTINE_TAG,
)
from l3.durable_store import DurableJsonStore

logger = logging.getLogger(__name__)


def _journal(path: str | None = None) -> DurableJsonStore:
    """Return the durable promotion journal (data_dir/memory/... by default)."""
    from l1.kernel.paths import data_dir as _data_dir

    p = Path(path) if path else Path(_data_dir()) / "memory" / "skill_promotions.json"
    return DurableJsonStore(p, kind="l3a_skill_promotion")


def promote_skill_transaction(
    candidate_id: str,
    skill_data: dict,
    skill_name: str | None = None,
    *,
    sm: Any = None,
    store: Any = None,
    journal_path: str | None = None,
) -> dict:
    """Promote a validated candidate into the skill library atomically.

    Args:
        candidate_id: validated candidate in the R4 ledger.
        skill_data: full skill record payload handed to SkillManager.
        skill_name: library name; defaults to ``skill_data["name"]``.
        sm: SkillManager (defaults to the process singleton).
        store: CandidateStore (defaults to the process singleton).
        journal_path: override for the durable journal file (tests).

    Returns:
        dict with success flag, the skill name, and per-step outcomes.
        Idempotent: re-promoting an already-promoted pair reports
        ``{"success": True, "idempotent": True}``.
    """
    from l1.kernel.skill import get_skill_manager as _gsm
    from l3.memory.r4_candidate_store import get_candidate_store as _gcs

    sm = sm or _gsm()
    store = store or _gcs()
    name = skill_name or str(skill_data.get("name") or "")
    if not candidate_id or not name:
        return {"success": False, "error": "candidate_id and skill name required"}

    jr = _journal(journal_path)
    try:
        jdata = jr.read()
    except Exception as e:  # noqa: BLE001 — fail closed on unreadable journal
        return {"success": False, "error": f"promotion journal unavailable: {e}"}

    done = jdata.get("done", {})
    if done.get(candidate_id) == name and sm.get(name):
        return {"success": True, "idempotent": True, "skill": name, "candidate_id": candidate_id}

    prior = sm.get(name)
    jdata.setdefault("pending", {})[candidate_id] = {"skill": name, "phase": "begin", "ts": time.time()}
    jr.write(jdata)

    reg = sm.register(name, dict(skill_data), internal=True)
    if not reg.get("success"):
        jdata["pending"].pop(candidate_id, None)
        jdata["failed"] = jdata.get("failed", [])[-9:] + [{"candidate_id": candidate_id, "error": reg.get("error")}]
        jr.write(jdata)
        return {"success": False, "error": f"library register failed: {reg.get('error')}", "skill": name}

    tr = store.transition(candidate_id, "promoted", skill_name=name)
    if not tr.get("success"):
        # Compensate: restore the pre-transaction library state.
        if prior is None:
            sm.delete(name, internal=True)
        else:
            sm.update(name, prior, internal=True)
        jdata["pending"].pop(candidate_id, None)
        jdata["failed"] = jdata.get("failed", [])[-9:] + [{"candidate_id": candidate_id, "error": tr.get("error")}]
        jr.write(jdata)
        return {
            "success": False,
            "error": f"ledger transition failed: {tr.get('error')}",
            "skill": name,
            "compensated": True,
        }

    pending = jdata.get("pending", {})
    pending.pop(candidate_id, None)
    done[candidate_id] = name
    jdata["done"] = done
    jdata["pending"] = pending
    jr.write(jdata)
    logger.info("skill_promotion: %s → %s (tx complete)", candidate_id, name)
    return {"success": True, "skill": name, "candidate_id": candidate_id}


# ── Canary automation (P1.4) ──


def evaluate_canary(
    metrics: dict,
    *,
    min_trials: int = SKILL_CANARY_MIN_TRIALS,
    min_success_rate: float = SKILL_CANARY_MIN_SUCCESS_RATE,
    max_latency_ms: int = SKILL_CANARY_MAX_LATENCY_MS,
) -> dict:
    """Pure canary decision from a metrics map (no side effects).

    Args:
        metrics: ``{injected, useful, avg_latency_ms?}`` — counters from
            the injection feedback path; latency dimension optional.
        min_trials: injections required before a verdict may quarantine.
        min_success_rate: floor on useful/injected once trials are met.
        max_latency_ms: ceiling on average latency; 0 disables the check.

    Returns:
        ``{"pass": bool, "reasons": [str], "trials_met": bool}`` — reasons
        list every tripped threshold (TS-mirrorable plain strings).
    """
    injected = int(metrics.get("injected", 0) or 0)
    useful = int(metrics.get("useful", 0) or 0)
    trials_met = injected >= min_trials
    reasons: list[str] = []
    if not trials_met:
        reasons.append(f"insufficient_trials:{injected}<{min_trials}")
        return {"pass": True, "reasons": [], "trials_met": False}
    rate = (useful / injected) if injected else 0.0
    if rate < min_success_rate:
        reasons.append(f"success_rate:{rate:.2f}<{min_success_rate}")
    if max_latency_ms > 0:
        lat = metrics.get("avg_latency_ms")
        if lat is not None and float(lat) > max_latency_ms:
            reasons.append(f"latency_ms:{float(lat):.0f}>{max_latency_ms}")
    return {"pass": not reasons, "reasons": reasons, "trials_met": True}


def quarantine_skill(
    name: str,
    reasons: list[str],
    *,
    sm: Any,
    archive_cb: Any | None = None,
) -> dict:
    """Quarantine a failing canary: archive evidence + deprecate + tag.

    Args:
        name: the skill under observation.
        reasons: evaluator reason strings (kept verbatim as evidence).
        sm: SkillManager instance.
        archive_cb: optional callable(name, record) persisting evidence to
            R4 before mutation (mirrors the verify-gate pattern).

    Returns:
        dict with success flag and the applied status.
    """
    rec = sm.get(name)
    if not rec:
        return {"success": False, "error": f"unknown skill: {name}"}
    if archive_cb is not None:
        try:
            archive_cb(name, rec)
        except Exception as e:  # noqa: BLE001 — evidence failure must not block quarantine
            logger.debug("skill_promotion: canary archive failed for %s: %s", name, e)
    tags = list(rec.get("tags") or [])
    if SKILL_CANARY_QUARANTINE_TAG not in tags:
        tags.append(SKILL_CANARY_QUARANTINE_TAG)
    upd = sm.update(name, {"status": "deprecated", "tags": tags}, internal=True)
    ok = bool(upd.get("success"))
    logger.warning("skill_promotion: canary quarantined %s (%s)", name, ";".join(reasons))
    return {"success": ok, "status": "deprecated" if ok else "unknown", "reasons": reasons}
