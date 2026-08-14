"""API handler mixin — security check / stats and posture-mode handlers.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations


def security_check(body: dict) -> dict:
    """Run a full security check for an action."""
    from l3.services.central_security import get_center

    return get_center().check_all(
        action=body.get("action", ""),
        agent_id=body.get("agent_id", ""),
        target=body.get("target", ""),
        args=body.get("args", {}),
        tool_name=body.get("tool_name", ""),
        user_token=body.get("user_token", ""),
    )


def security_stats(body: dict | None = None) -> dict:
    """Central security statistics."""
    from l3.services.central_security import get_center

    return get_center().stats()


def security_mode_get(body: dict | None = None) -> dict:
    """System security-posture status."""
    from l3.tool_system.security_mode import security_status

    return security_status()


def security_mode_set(body: dict) -> dict:
    """Switch security posture (productive | security-test)."""
    from l3.tool_system.security_mode import set_security_mode

    return set_security_mode(
        body.get("mode", ""),
        confirmed=bool(body.get("confirm_risk")),
        source="api",
    )


def security_mode_notifications(body: dict | None = None) -> dict:
    """Recent bypass-detection warnings + mode changes (pull channel)."""
    from l3.tool_system.security_mode import security_notifications

    b = body or {}
    try:
        limit = int(b.get("limit", 0))
    except (TypeError, ValueError):
        limit = 0
    event_type = str(b.get("event_type", ""))
    items = security_notifications(limit=limit, event_type=event_type)
    return {"success": True, "count": len(items), "notifications": items}


def security_alerts(body: dict | None = None) -> dict:
    """Danger-action broadcasts (auto-approved / blocked high-danger calls, pull channel)."""
    from l1.kernel.notify import get_notify

    b = body or {}
    try:
        limit = int(b.get("limit", 0))
    except (TypeError, ValueError):
        limit = 0
    items = get_notify().recent(limit=limit)
    return {"success": True, "count": len(items), "alerts": items}


def tool_mode_get(body: dict | None = None) -> dict:
    """Current tool mode."""
    from l3.tool_system.tool_mode import get_mode

    return {"mode": get_mode()}


def tool_mode_set(body: dict) -> dict:
    """Toggle / set tool mode."""
    from l3.tool_system.tool_mode import set_mode

    return set_mode(body.get("mode", "toggle"))


def harness_mode_get(body: dict | None = None) -> dict:
    """Harness mode status."""
    from l3.tool_system.harness import harness_status

    return harness_status()


def harness_mode_set(body: dict) -> dict:
    """Set harness mode with risk confirmation."""
    from l3.tool_system.harness import set_harness_mode

    return set_harness_mode(body.get("mode", ""), confirmed=bool(body.get("confirm_risk")), source="api")


def security_evidence_chains(body: dict | None = None) -> dict:
    """Evidence-chain index (newest first) with verdict previews."""
    from l3.tool_system.security_evidence import get_evidence

    b = body or {}
    try:
        limit = int(b.get("limit", 0))
    except (TypeError, ValueError):
        limit = 0
    rows = get_evidence().chains(limit=limit)
    for row in rows:
        row["verdict"] = get_evidence().analyze(row["chain_id"]).get("verdict", "clean")
    return {"success": True, "count": len(rows), "chains": rows}


def security_evidence_query(body: dict | None = None) -> dict:
    """Query evidence points (chain_id / skill / phase / decision filters)."""
    from l3.tool_system.security_evidence import get_evidence

    b = body or {}
    try:
        limit = int(b.get("limit", 0))
    except (TypeError, ValueError):
        limit = 0
    items = get_evidence().query_evidence(
        chain_id=str(b.get("chain_id", "")),
        skill=str(b.get("skill", "")),
        phase=str(b.get("phase", "")),
        decision=str(b.get("decision", "")),
        limit=limit,
    )
    return {"success": True, "count": len(items), "evidence": items}


def security_evidence_report(body: dict | None = None) -> dict:
    """Evidence-chain analysis report (verdict + timeline + findings + fixity)."""
    from l3.tool_system.security_evidence import get_evidence

    b = body or {}
    return get_evidence().report(str(b.get("chain_id", "")))


def security_evidence_cross_analyze(body: dict | None = None) -> dict:
    """Cross-chain aggregate analysis (optionally filtered by kind).

    Body: ``{"kind": "probe"}`` (omit for all kinds). Aggregates verdict
    and decision counts plus top skills across chains — a posture-level
    overview for the operator / L3A decision layer.
    """
    from l3.tool_system.security_evidence import get_evidence

    b = body or {}
    return get_evidence().cross_chain_analyze(kind=str(b.get("kind", "")))


def posture_matrix_get(body: dict | None = None) -> dict:
    """GET /api/v2/posture — posture matrix status (no raw whitelists)."""
    from l3.tool_system.posture_matrix import get_posture_matrix

    return {"success": True, "posture": get_posture_matrix().status()}


def posture_matrix_set(body: dict) -> dict:
    """PUT /api/v2/posture — set one domain's offensive flag + whitelist.

    Body: ``{"domain": "attack", "offensive": true, "target_whitelist": ["10.0.0.0/8"]}``.
    Enforcing offensive posture without a whitelist is rejected; harness
    'minimal' is forbidden while offensive (see PostureMatrix).
    """
    from l3.tool_system.posture_matrix import get_posture_matrix

    domain = str(body.get("domain", ""))
    if not domain:
        return {"success": False, "error": "domain required"}
    offensive = bool(body.get("offensive", False))
    wl = body.get("target_whitelist")
    wl_list = [str(t) for t in wl] if isinstance(wl, list) else None
    return get_posture_matrix().set_domain(domain, offensive, wl_list)


def posture_api_enabled_set(body: dict) -> dict:
    """PUT /api/v2/posture/api — flip the posture API master switch."""
    from l3.tool_system.posture_matrix import get_posture_matrix

    return get_posture_matrix().set_api_enabled(bool(body.get("enabled", False)))


def departments_status(body: dict | None = None) -> dict:
    """GET /api/v2/departments — department division status."""
    from l3.cell.department import get_department_manager

    b = body or {}
    try:
        cell_count = int(b.get("cell_count", 0)) or None
    except (TypeError, ValueError):
        cell_count = None
    return {"success": True, **get_department_manager().status(cell_count=cell_count)}


def departments_suggest(body: dict) -> dict:
    """POST /api/v2/departments/suggest — L3A-assisted department designation.

    Body: ``{"intent": "run the test suite", "domain": "test"}``. Returns a
    suggested department type (general/build/test/review); the final choice
    stays config-driven.
    """
    from l3.cell.department import suggest_department

    intent = str(body.get("intent", ""))
    if not intent:
        return {"success": False, "error": "intent required"}
    return {"success": True, "suggestion": suggest_department(intent, domain=str(body.get("domain", "")))}


def secretary_status(body: dict | None = None) -> dict:
    """GET /api/v2/l3a/secretary — L3A-C secretary status (mode/score)."""
    from l3.cell.peers.l3a.secretary import get_secretary

    sec = get_secretary()
    return {"success": True, "mode": sec.mode(), "score": sec.score()}


def memory_filter_get(body: dict | None = None) -> dict:
    """GET /api/v2/memory/filter — memory domain-filter switch state (M1)."""
    from l3.memory.memory_domain_filter import get_memory_filter

    return {"success": True, "filter": get_memory_filter().status()}


def memory_filter_set(body: dict) -> dict:
    """PUT /api/v2/memory/filter — enable/disable memory domain filtering (M1).

    Body: ``{"enabled": true, "fine_grained": true}`` (either optional).
    Both switches are operator-controlled, never code-embedded.
    """
    from l3.memory.memory_domain_filter import get_memory_filter

    return get_memory_filter().set_switches(
        enabled=body.get("enabled"),
        fine_grained=body.get("fine_grained"),
    )


def l3a_decision_layer_get(body: dict | None = None) -> dict:
    """GET /api/v2/l3a/decision-layer — L3A's decision-layer role (D2)."""
    from l3.cell.peers.l3a import get_daemon

    b = body or {}
    try:
        cell_count = int(b.get("cell_count", 0)) or None
    except (TypeError, ValueError):
        cell_count = None
    return {"success": True, "layer": get_daemon().decision_layer(cell_count=cell_count)}


def l3a_delegate_post(body: dict) -> dict:
    """POST /api/v2/l3a/delegate — L3A commissions a decision task (D2).

    Body: ``{"decision": "...", "spec": "secretary"}``. Second-decision-
    layer mode: L3A delegates execution to a secretary/decision body
    instead of running everything itself.
    """
    from l3.cell.peers.l3a import get_daemon

    decision = str(body.get("decision", ""))
    if not decision:
        return {"success": False, "error": "decision required"}
    return get_daemon().delegate(
        decision,
        target=str(body.get("target", "")),
        spec=str(body.get("spec", "secretary")),
    )


def secretary_update(body: dict) -> dict:
    """PUT /api/v2/l3a/secretary — runtime toggle for the L3A-C secretary.

    Body (all optional)::

        {"enabled": true|false,      # override the active switch (null → settings default)
         "threshold": 5,             # adjust the assist→peer threshold (0 → params default)
         "mode": "auto"|"assist"|"peer"}  # pin the mode (auto = score-driven)

    The secretary's enable / upgrade is operator-controllable through this
    API — never code-embedded automatic switching alone.
    """
    from l3.cell.peers.l3a.secretary import get_secretary

    sec = get_secretary()
    if "enabled" in body:
        r = sec.set_enabled(body["enabled"] if body["enabled"] is not None else None)
        if not r.get("success"):
            return r
    if "threshold" in body:
        try:
            threshold = int(body["threshold"])
        except (TypeError, ValueError):
            return {"success": False, "error": "threshold must be an integer"}
        r = sec.set_threshold(threshold)
        if not r.get("success"):
            return r
    if "mode" in body:
        r = sec.set_mode(str(body["mode"]))
        if not r.get("success"):
            return r
    return {"success": True, "status": sec.status()}


def secretary_contribute(body: dict) -> dict:
    """POST /api/v2/l3a/secretary/contribute — record a secretary contribution.

    Body: ``{"kind": "analysis", "success": true, "card_id": "card-1"}``.
    Crossing the capability threshold upgrades assist → peer.
    """
    from l3.cell.peers.l3a.secretary import get_secretary

    kind = str(body.get("kind", ""))
    if not kind:
        return {"success": False, "error": "kind required"}
    return get_secretary().contribute(
        kind,
        success=bool(body.get("success", True)),
        card_id=str(body.get("card_id", "")),
        detail=str(body.get("detail", "")),
    )


def review_threshold_get(body: dict | None = None) -> dict:
    """GET /api/v2/review/threshold — review pipeline disposition settings."""
    from l3.services.review_pipeline import get_review_pipeline

    return {"success": True, "settings": get_review_pipeline().threshold()}


def review_threshold_set(body: dict) -> dict:
    """PUT /api/v2/review/threshold — adjust the small-change bypass threshold.

    Body: ``{"max_small_lines": 50, "enabled": true, "autofix": true}``.
    Changes at or below the threshold are fixed in place by the review
    department; larger changes route to rework + L3A report.
    """
    from l3.services.review_pipeline import get_review_pipeline

    pipe = get_review_pipeline()
    if "max_small_lines" in body:
        r = pipe.set_threshold(int(body.get("max_small_lines", 50)))
        if not r.get("success"):
            return r
    if "enabled" in body or "autofix" in body:
        pipe.set_enabled(
            bool(body.get("enabled", True)),
            autofix=body.get("autofix"),
        )
    return {"success": True, "settings": pipe.threshold()}


def diff_persist_get(body: dict | None = None) -> dict:
    """GET /api/v2/diff/persist — diff-persist store statistics."""
    from l4.sandbox.diff_persist import get_diff_persist

    return {"success": True, "stats": get_diff_persist().stats()}


def diff_persist_set(body: dict) -> dict:
    """PUT /api/v2/diff/persist — enable/disable the frontend-heavy diff store.

    Body: ``{"enabled": true}``. Only the heavy frontend should enable it;
    TUI / terminal runs keep it off to avoid the cache-architecture cost.
    """
    from l4.sandbox.diff_persist import get_diff_persist

    return get_diff_persist().set_enabled(bool(body.get("enabled", False)))


def diff_persist_list(body: dict | None = None) -> dict:
    """GET /api/v2/diff/stitch — stitched diffs for frontend consumption.

    Body: ``{"limit": 50}``. Returns recent stitched diff records (diff_id,
    path, meta, stitched text) from the ring buffer — the human-review
    surface of the two-faced diff system.
    """
    from l4.sandbox.diff_persist import get_diff_persist

    b = body or {}
    try:
        limit = int(b.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    return {"success": True, "count": limit, "stitched": get_diff_persist().list_stitched(limit=limit)}


def presentation_mode_get(body: dict | None = None) -> dict:
    """Tool presentation mode status (native / code / both)."""
    from l3.tool_system.tool_presentation import presentation_status

    return presentation_status()


def presentation_mode_set(body: dict) -> dict:
    """Switch the tool presentation mode (native / code / both)."""
    from l3.tool_system.tool_presentation import set_presentation_mode

    return set_presentation_mode(body.get("mode", ""), source="api")


def memory_corpus_export(body: dict | None = None) -> dict:
    """Export the M4 correction corpus (refined memory + identity/domain + logs).

    Args:
        body: optional dict with ``limit`` (max samples; 0 = default).

    Returns:
        dict with success flag, sample count, and the corpus samples.
    """
    from l3.memory.memory_record_source import export_corpus

    return export_corpus(limit=int((body or {}).get("limit", 0) or 0))


def memory_rc_analysis(body: dict | None = None) -> dict:
    """Correlate reference-channel memory events with refined records.

    Args:
        body: optional dict with ``limit`` (max RC events; 0 = default cap).

    Returns:
        dict with per-cell/per-type/per-ring aggregates + correlation ratio.
    """
    from l3.memory.memory_record_source import analyze_rc_correlation

    return analyze_rc_correlation(limit=int((body or {}).get("limit", 100) or 100))


def memory_digest_get(body: dict | None = None) -> dict:
    """Conversation digest-cache switch state (B1)."""
    from l3.agent.digest_cache import digest_status

    return digest_status()


def memory_digest_set(body: dict) -> dict:
    """Enable/disable the conversation digest cache (B1)."""
    from l3.agent.digest_cache import set_digest_switches

    enabled = body.get("enabled")
    max_chars = body.get("max_chars")
    return set_digest_switches(
        enabled=None if enabled is None else bool(enabled),
        max_chars=None if max_chars is None else int(max_chars),
    )


def memory_tool_result_get(body: dict | None = None) -> dict:
    """Tool-result offload-cache switch state (B2)."""
    from l3.agent.tool_result_cache import tool_result_status

    return tool_result_status()


def memory_tool_result_set(body: dict) -> dict:
    """Enable/disable the tool-result offload cache (B2)."""
    from l3.agent.tool_result_cache import set_tool_result_switches

    enabled = body.get("enabled")
    max_chars = body.get("max_chars")
    return set_tool_result_switches(
        enabled=None if enabled is None else bool(enabled),
        max_chars=None if max_chars is None else int(max_chars),
    )


def memory_sensitive_get(body: dict | None = None) -> dict:
    """Sensitive-info bypass detection switch state (B6)."""
    from l3.agent.sensitive_detect import sensitive_status

    return sensitive_status()


def memory_sensitive_set(body: dict) -> dict:
    """Enable/disable sensitive-info bypass detection (B6)."""
    from l3.agent.sensitive_detect import set_sensitive_switches

    enabled = body.get("enabled")
    return set_sensitive_switches(enabled=None if enabled is None else bool(enabled))


def memory_compression_guard_get(body: dict | None = None) -> dict:
    """Compression guard state: recursion threshold + breaker (B6)."""
    from l3.agent.compression_guard import guard_status

    return guard_status()


def memory_compression_guard_set(body: dict) -> dict:
    """Set the recursion threshold / breaker switch (B6)."""
    from l3.agent.compression_guard import set_guard_switches

    threshold = body.get("recursion_threshold")
    breaker = body.get("breaker_enabled")
    return set_guard_switches(
        recursion_threshold=None if threshold is None else int(threshold),
        breaker_enabled=None if breaker is None else bool(breaker),
    )
