"""Boot step — Cell creation with configured agents.

Extracted from ``boot_steps.py``.  ``_create_cell`` builds the default
Cell, binds skills from config, registers agents with the scheduler and
VFS, and wires the CardRegistry dispatcher + PendingQueue callbacks.
"""

from __future__ import annotations

import logging

from l1.kernel.params.agent import DEFAULT_CELL_ID

logger = logging.getLogger(__name__)


def _create_cell(agent_config: list[tuple[str, str, list[str]]] | None = None) -> dict:
    """Create Cell with configured agents + Scout pool."""
    from l1.kernel import register_process
    from l1.kernel.params.agent import AGENT_PRIORITY
    from l1.kernel.vfs import MountType, get_vfs
    from l3.agent.scout import get_pool as get_scout_pool
    from l3.cell import get_cell
    from l3.scheduler.scheduler import get_time_scheduler
    from l3.services.fault_tolerance import get_service as get_ft

    cell = get_cell(DEFAULT_CELL_ID)
    get_ft().start()

    # ── Skill binding from config (inject back into Cell) — optional; missing → global pool ──
    try:
        from l3.config.settings_center import get_center as _gc

        cell_skills = _gc().get("cell.skills", {})
        if isinstance(cell_skills, dict):
            names = cell_skills.get(DEFAULT_CELL_ID) or cell_skills.get("*")
            if names:
                r = cell.bind_skills(names)
                logger.info("boot: bound %d skills to cell %s", r.get("bound", 0), DEFAULT_CELL_ID)
    except Exception as e:
        logger.debug("boot: skill binding skipped: %s", e)

    registered = []
    for agent_id, role, territory in agent_config or []:
        cell.add_agent(agent_id, role=role, territory=territory, auto_boot=True)
        pid = register_process(agent_id, role=role, ring=1)
        get_time_scheduler().register(agent_id, priority=AGENT_PRIORITY.get(role, 5))
        get_ft().heartbeat(agent_id)
        registered.append({"agent": agent_id, "pid": pid})
        for t in territory:
            get_vfs().mount(f"/{agent_id}/{t.lstrip('/')}", MountType.PROJECT, min_ring=1, read_only=False)

    get_scout_pool()

    # Register Cell with CardRegistry dispatcher + PendingQueue callback
    try:
        from l3.card.card_registry import get_registry

        reg = get_registry()
        reg.register_cell(DEFAULT_CELL_ID, cell.territory)
        reg.set_cell_resolver(lambda cid: get_cell(cid))
        reg.start_dispatcher()
        # Wire PendingQueue approve → CardRegistry.restore_card
        from l3.card.pending_queue import get_queue

        pq = get_queue()
        pq.set_on_approve(lambda cid: reg.restore_card(cid))
    except Exception as e:
        logger.warning("card registry setup: %s", e)

    return {
        "success": True,
        "cell_id": DEFAULT_CELL_ID,
        "agents": [a[0] for a in agent_config] if agent_config else [],
        "registered": registered,
    }
