"""Boot step — constitution loading and default template.

Extracted from ``boot_steps.py``.  ``_load_constitution`` loads
``.praxis-rules.md`` into both the territory store and the rule engine,
restores runtime-persisted custom rules, and injects the security
posture/metric/harness providers into the L1 layers; ``_default_constitution``
returns the blank template used on first boot.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


def _load_constitution() -> dict:
    """Load constitution from .praxis-rules.md into both territory and rule engine.

    Also restores custom rules previously persisted to SettingsCenter L3
    (from runtime API updates) so they survive restarts.
    """
    from pathlib import Path

    from l1.kernel.constitution import TerritoryConstitution, get_constitution, load_territory
    from l1.kernel.params.agent import CONSTITUTION_ENV_VAR
    from l1.kernel.paths import get_paths

    constitution_path = get_paths().constitution_file
    path = Path(os.environ.get(CONSTITUTION_ENV_VAR, constitution_path))
    result: dict[str, Any] = {"source": str(path) if path.exists() else "none"}
    try:
        if path.exists():
            c = load_territory(str(path))
            if not c or not isinstance(c, TerritoryConstitution):
                result["assembly_mode"] = True
            else:
                engine_load = get_constitution().load(str(path))
                if not engine_load.get("success"):
                    logger.warning("constitution engine load failed: %s", engine_load.get("error", ""))
                result["assembly_mode"] = False
                result["rules"] = engine_load.get("rules", 0)
                result["custom"] = engine_load.get("custom", 0)
        else:
            result["assembly_mode"] = True

        # Restore custom rules from SettingsCenter L3 (runtime persistence)
        try:
            from l3.config.settings_center import get_center

            sc = get_center()
            custom_rules = sc.get("constitution.custom_rules")
            if custom_rules and isinstance(custom_rules, list) and len(custom_rules) > 0:
                r = get_constitution().update_rules(custom_rules)
                result["restored"] = r.get("updated", 0)
                logger.info("constitution: restored %d custom rules from L3", r.get("updated", 0))
        except Exception:
            logger.debug("boot: constitution restore failed")

        # Inject the security-posture provider (kernel never imports L3; the
        # constitution's §9.2 skill.offensive_posture rule reads it to gate
        # offensive-skill use by system posture).
        try:
            from l1.kernel.constitution import set_posture_provider
            from l3.tool_system.security_mode import get_posture

            set_posture_provider(get_posture)
            result["posture_provider"] = True
        except Exception as e:
            logger.debug("boot: posture provider inject skipped: %s", e)

        # Inject the posture provider into GateChain too — G4 escalation skips
        # the L3 review WARN for high-danger tools when full_power is granted.
        try:
            from l1.kernel.gatechain import get_gatechain
            from l3.tool_system.security_mode import get_posture as _gp2

            get_gatechain().set_posture_provider(_gp2)
        except Exception as e:
            logger.debug("boot: gatechain posture provider inject skipped: %s", e)

        # Inject the metric sink into the L1 layers (constitution §9.2 BLOCK,
        # gatechain G4 full_power) — L1 never imports L3; the sink forwards
        # security.* counters to StatsCenter via security_mode helper.
        try:
            from l1.kernel.constitution import set_metric_sink
            from l1.kernel.gatechain import get_gatechain as _gc3
            from l3.tool_system.security_evidence import ensure_listener, record_from_metric
            from l3.tool_system.security_mode import ingest_security_metric

            def _sink(name: str, value: float, tags: dict | None = None) -> None:
                ingest_security_metric(name, value, tags)
                # Evidence chain: gatechain G4 / constitution decisions become
                # evidence points (side-channel, never breaks the gate).
                record_from_metric(name, value, tags)

            set_metric_sink(_sink)
            _gc3().set_metric_sink(_sink)
            # Attach the L1-sourced event listener (offensive-policy changes).
            ensure_listener()
        except Exception as e:
            logger.debug("boot: metric sink inject skipped: %s", e)

        # Inject the harness-mode provider into GateChain — G4 treats a
        # deliberate harness downgrade (semi/minimal, operator-confirmed) as
        # explicit authorization and auto-approves high-danger tools there.
        try:
            from l3.tool_system.harness import get_harness_mode

            _gc3().set_harness_provider(lambda: str(get_harness_mode())[:64])
        except Exception as e:
            logger.debug("boot: gatechain harness provider inject skipped: %s", e)

        # Register the capability gate as the terminal GateChain stage — a
        # typed deny record (or an expired/spent one-shot) overrides any
        # earlier auto-approval from G4; no record falls through to the
        # existing policy gates unchanged.
        try:

            def _capability_gate(ctx, gc):
                from l3.services.capability_store import get_capability_store as _store

                decision = _store().check(ctx["agent_id"], f"tool:{ctx['tool']}")
                steps = ctx["steps"]
                if decision["decision"] == "deny":
                    steps.append(
                        {
                            "gate": "capability",
                            "result": "BLOCK",
                            "reason": f"typed deny record ({','.join(decision['records'])})",
                        }
                    )
                    from l1.kernel.gatechain import GateResult

                    return steps, GateResult.BLOCK
                steps.append({"gate": "capability", "result": "PASS"})
                return steps, ctx.get("_overall", GateResult.PASS)

            get_gatechain().register_gate("capability", _capability_gate)
        except Exception as e:
            logger.debug("boot: capability gate register skipped: %s", e)
        # query()/stats()/export() can cover the security domain (Phase E).
        try:
            from l3.services.record_center import get_record_center
            from l3.tool_system.security_mode import security_notifications

            def _sec_query(limit: int = 0) -> list:
                return security_notifications(limit=limit)

            def _sec_stats() -> dict:
                chains = 0
                try:
                    from l3.tool_system.security_evidence import get_evidence

                    chains = len(get_evidence().chains())
                except Exception:
                    pass
                return {"notifications": len(security_notifications()), "evidence_chains": chains}

            get_record_center().register_source(
                "security",
                query_fn=_sec_query,
                stats_fn=_sec_stats,
                export_fn=_sec_query,
            )
        except Exception as e:
            logger.debug("boot: record_center security source register skipped: %s", e)

        # 2.1-D7: diff line-precise record source (feeds RC collection).
        try:
            from l3.services.diff_record_source import register_diff_source

            register_diff_source()
        except Exception as e:
            logger.debug("boot: record_center diff source register skipped: %s", e)

        # Phase 3 M4: refined-memory record source (correction corpus for
        # external training models — memory + identity/Cell features + logs).
        try:
            from l3.memory.memory_record_source import register_memory_source

            register_memory_source()
        except Exception as e:
            logger.debug("boot: record_center memory source register skipped: %s", e)

        # Auto-trigger territory discussion if constitution is blank
        if result.get("assembly_mode"):
            try:
                logger.info("constitution: blank — triggering territory discussion")
                from l3.card.issue import IssueCard, get_table

                card = IssueCard(
                    id=f"issue-boot-{int(time.time())}",
                    title="Determine Cell territory division",
                    intent="The constitution has no territory definitions. "
                    "Each Cell must propose its territory assignment.",
                    domain="cluster",
                    cell_id="cell-1",
                )
                get_table().submit(card)
                from l3.discussion.issue_orchestrator import get_orchestrator

                orch = get_orchestrator()
                r = orch.start_discussion(card)
                if r.get("success"):
                    orch.register_cell(r["session_id"], "cell-1")
                    result["discussion_session"] = r["session_id"]
                    logger.info("constitution: started discussion %s", r["session_id"])
            except Exception as e:
                logger.warning("constitution: auto-discuss failed: %s", e)

        return {"success": True, **result}
    except Exception as e:
        logger.error("constitution load error: %s", e)
        return {"success": False, "error": str(e), "assembly_mode": True}


def _default_constitution() -> str:
    """Return the default constitution template for a fresh boot."""
    return """# NOMOS Constitution (default)
G1: workspace_fingerprint
G2: identity_verification
G3: permission_check
G4: compliance_scan
G5: report_decision
"""
