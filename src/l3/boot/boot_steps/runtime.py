"""Boot steps — runtime subsystem initialization.

Extracted from ``boot_steps.py``.  Owns the skills/network/HTN/capability
detector step, the memory/archive/R4/L3A step, and the SystemBus root
mount step.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _init_skills_and_network() -> dict:
    """Init skills, network kernel, HTN planner, capability detector."""
    results: dict[str, Any] = {}
    from l1.kernel.skill import get_skill_manager

    n = get_skill_manager().load_builtin()
    if n > 0:
        logger.info("loaded %d skills", n)
    try:
        from l1.kernel.net import get_net

        get_net().start()
        results["network"] = "ok"
    except Exception as e:
        results["network"] = f"skip: {e}"
    try:
        from l3.bus.htn_planner import get_service as get_htn

        get_htn()
        results["htn_planner"] = "ok"
    except Exception as e:
        results["htn_planner"] = f"error: {e}"
    # Warm capability detector — async probe all registered providers
    try:
        from l1.kernel.model_registry import get_registry
        from l3.services.model_strategy import get_detector

        det = get_detector()
        n_probed = det.probe_all_registered(get_registry())
        results["capability_detector"] = f"{n_probed} providers submitted"
    except Exception as e:
        results["capability_detector"] = f"skip: {e}"
    # B4: register the card-completion → tool-stats linkage bridge so the
    # completion listener is live at runtime (idempotent).
    try:
        from l3.services.card_tool_stats import wire_card_tool_stats

        results["card_tool_stats"] = wire_card_tool_stats().get("success", False)
    except Exception as e:
        results["card_tool_stats"] = f"skip: {e}"
    return results


def _init_memory_and_archive() -> dict:
    """Init MemoryManager, Archive, R4Agent, IssueTable, CredentialVault."""
    results: dict[str, Any] = {}
    try:
        from l3.memory.memory import get_memory

        mem = get_memory()
        mem.set_persist_dir("memories")
        mr = mem.restore()
        results["memory_restore"] = f"{mr.get('restored', 0)} entries"
        # Sync operator switches from settings (praxis.yaml → module state):
        # compaction mode, premise guard, inject dedup. Every setter degrades
        # to the module default when the setting is absent.
        try:
            from l1.kernel.settings import get_settings
            from l3.memory.memory_context import set_inject_dedup
            from l3.memory.memory_extract import set_compaction_mode
            from l3.memory.premise_guard import set_premise_guard

            s = get_settings()
            set_compaction_mode(str(s.get("memory.compaction_mode", "deterministic")))
            set_premise_guard(enabled=bool(s.get("memory.premise_guard", True)))
            set_inject_dedup(enabled=bool(s.get("memory.inject_dedup", True)))
            results["memory_switches"] = "synced"
        except Exception as e:
            results["memory_switches"] = f"skip: {e}"
        # Wire swapper to memory service
        try:
            from l1.kernel.swapper import get_swapper

            swp = get_swapper()
            swp.set_memory(mem)
            results["swapper_wired"] = "ok"
        except Exception as e:
            results["swapper_wired"] = f"skip: {e}"
    except Exception as e:
        results["memory_restore"] = f"skip: {e}"
    try:
        from l3.tools._archive import init_archive

        init_archive()
        results["archive_init"] = "ok"
    except Exception as e:
        logger.warning("archive init failed: %s", e)
        results["archive_init"] = f"skip: {e}"
    try:
        from l3.memory.archive_orchestrator import ring3_from_archive

        n = ring3_from_archive(get_memory())
        results["archive_restore"] = f"{n} entries"
    except Exception as e:
        results["archive_restore"] = f"skip: {e}"
    try:
        from l3.memory.r4_agent import get_r4_agent, start_r4_agent

        r4 = get_r4_agent()
        try:
            from l3.cell import get_cell

            cell = get_cell("default")
            if cell and getattr(cell, "_pmu", None):
                r4.set_pmu(cell._pmu)
        except Exception as e:
            logger.debug("r4 pmu wire skipped: %s", e)
        start_r4_agent()
        results["r4_agent"] = "started"
    except Exception as e:
        results["r4_agent"] = f"error: {e}"
    try:
        from l3.cell.peers.l3a import start_l3a_daemon

        start_l3a_daemon()
        results["l3a_daemon"] = "started"
    except Exception as e:
        results["l3a_daemon"] = f"error: {e}"
    for mod, module_path, name in [
        ("issue", "l3.card.issue", "get_table"),
        ("cache_doc", "l3.memory.cache_doc", "get_store"),
        ("credential_vault", "l4.vault.credential_vault", "init_vault"),
        ("tool_mode", "l3.tool_system.tool_mode", "init_tool_mode"),
        ("central_security", "l3.services.central_security", "get_center"),
        ("central_memory", "l3.memory.central_memory", "get_center"),
        ("central_plugin", "l3.services.central_plugin", "get_center"),
        ("auth_service", "l4.vault.auth", "get_service"),
    ]:
        try:
            import importlib

            m = importlib.import_module(module_path)
            getattr(m, name)()
            results[mod] = "ok"
        except Exception as e:
            results[mod] = f"skip: {e}"
    return results


def _init_system_bus() -> dict:
    """Initialize SystemBus root with global service components.

    Registers EventBus, StatsCenter, RecordCenter, CentralController
    so they participate in the unified lifecycle and event routing.
    """
    results: dict[str, Any] = {}
    try:
        from l1.kernel.bus import get_root_bus

        root = get_root_bus()

        # Mount sub-buses
        gs = root.mount("global")

        # Register global components
        from l3.services.global_components import (
            CentralControllerComponent,
            EventBusComponent,
            RecordCenterComponent,
            StatsCenterComponent,
        )

        gs.register(StatsCenterComponent())
        gs.register(RecordCenterComponent())
        gs.register(EventBusComponent())
        gs.register(CentralControllerComponent())

        # The Cell bus will be mounted by _create_cell later

        gs.install()
        results["system_bus"] = "ok"
        results["components"] = [c.meta.name for c in gs.list()]
    except Exception as e:
        logger.warning("system_bus init: %s", e)
        results["system_bus"] = f"skip: {e}"
    return results
