"""Boot step — kernel core services and VFS initialization.

Extracted from ``boot_steps.py``.  ``_init_kernel_and_vfs`` warms the L1
kernel singletons, mounts the root VFS layout and flattens the loaded
config into the L2 SettingsCenter.
"""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel.params.kernel import SWAPPER_BOOT_INTERVAL

logger = logging.getLogger(__name__)


def _init_kernel_and_vfs() -> dict:
    """Init kernel core services + VFS + config + devices."""
    from l1.kernel import get_event_bus
    from l1.kernel.allocator import get_allocator
    from l1.kernel.constitution import get_constitution
    from l1.kernel.device import get_device_manager
    from l1.kernel.gatechain import get_gatechain, register_stagnation_callback
    from l1.kernel.swapper import get_swapper
    from l1.kernel.vfs import MountType, get_vfs

    # Wire the stagnation break_loop callback into GateChain G5 (L3 -> L1)
    try:
        from l3.agent.stagnation import get_detector as _get_detector

        register_stagnation_callback(_get_detector().break_loop)
    except Exception as e:
        logger.warning("boot: stagnation callback wiring failed: %s", e)

    results: dict[str, Any] = {}
    for name, fn in [
        ("constitution", get_constitution),
        ("event_bus", get_event_bus),
        ("allocator", get_allocator),
        ("gatechain", get_gatechain),
        ("swapper", lambda: get_swapper(interval=SWAPPER_BOOT_INTERVAL)),
    ]:
        try:
            fn()
            results[name] = "ok"
        except Exception as e:
            results[name] = f"error: {e}"

    vfs = get_vfs()
    for path, mtype, ro in [
        ("/project", MountType.PROJECT, False),
        ("/proc", MountType.SYSTEM, True),
        ("/tmp", MountType.TEMP, False),
    ]:
        vfs.mount(path, mtype, min_ring=1, read_only=ro, description=path.strip("/"))
    for path, mtype, ro in [
        ("/sys", MountType.VIRTUAL, True),
        ("/dev", MountType.VIRTUAL, True),
        ("/skills", MountType.VIRTUAL, True),
    ]:
        vfs.mount(path, mtype, min_ring=1, read_only=ro, description=path.strip("/"))

    # Config was already applied by the load_config boot step (handlers with
    # side effects: start_api, device registration, MCP import). Here we only
    # re-load + flatten into SettingsCenter L2 so this step stays pure and
    # the apply side effects run exactly once per boot.
    from l3.config.config_loader import load as _cfg_load
    from l3.config.settings_center import SettingsCenter, get_center

    try:
        _cfg_r = _cfg_load()
        if _cfg_r.get("success") and _cfg_r.get("data"):
            get_center().load_l2(SettingsCenter._flatten(_cfg_r["data"]))
    except Exception as e:
        logger.warning("boot config: %s", e)

    dm = get_device_manager()
    # Device registration is completed by the load_config step (cfg_devices,
    # praxis.yaml devices: section); nothing is hardcoded here because
    # re-registration is silently rejected by device_manager.
    dm.start_health_checks()
    return {"success": True, "results": results}
