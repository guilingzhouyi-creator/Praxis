"""Boot step — aggregate service initialization.

Extracted from ``boot_steps.py``.  ``_init_services`` runs the
kernel/runtime sub-steps, then warms the bus/resource/hook/log/CI
singletons and registers the boot event.
"""

from __future__ import annotations

import logging
from typing import Any

from .kernel import _init_kernel_and_vfs
from .runtime import _init_memory_and_archive, _init_skills_and_network

logger = logging.getLogger(__name__)


def _init_services() -> dict:
    """Initialize all kernel services."""
    results: dict[str, Any] = {}
    for sub_fn in [_init_kernel_and_vfs, _init_skills_and_network, _init_memory_and_archive]:
        try:
            r = sub_fn()
            results.update(r)
        except Exception as e:
            logger.error("boot sub-init failed: %s", e)
    # Initialize MonitorBus + MessageGate
    try:
        from l3.bus.monitor_bus import get_bus

        get_bus()  # warm singleton
        results["monitor_bus"] = "ok"
    except Exception as e:
        logger.warning("monitor_bus init: %s", e)
    try:
        from l3.bus.monitor_bus import MonitorEvent
        from l3.bus.monitor_bus import get_bus as _mb

        _mb().emit(MonitorEvent(type="system.boot", source="boot", severity="info", message="System booted"))
    except Exception:
        logger.debug("boot: boot event emit failed")
    # Initialize ResourceBuffer (crash recovery + background flush)
    try:
        from l3.resource_buffer.manager import get_manager

        get_manager()  # warm singleton, triggers recover()
        results["resource_buffer"] = "ok"
    except Exception as e:
        logger.warning("resource_buffer init: %s", e)

    # Register the code auto-format post-execute hook (config-gated in praxis.yaml)
    try:
        from l3.services.code_format import auto_format_hook
        from l3.tool_system.tool_pipeline import get_pipeline

        get_pipeline().register_post_execute_hook(auto_format_hook)
        results["code_format"] = "ok"
    except Exception as e:
        logger.warning("code_format hook register: %s", e)

    # Install LogService logging bridge (catches all logger.* calls)
    try:
        from l3.bus.log import get_service as _ls

        _ls().install_handler()
        results["log_handler"] = "ok"
    except Exception as e:
        logger.warning("log handler install: %s", e)

    # Register the card-triggered CI review daemon (config-gated in praxis.yaml)
    try:
        from l4.ci_review import get_service as _get_ci_review

        _get_ci_review().register_card_trigger()
        results["ci_review"] = "ok"
    except Exception as e:
        logger.warning("ci_review trigger register: %s", e)

    # Surface real failures (values starting with "error:") instead of hiding them
    failed = [k for k, v in results.items() if isinstance(v, str) and v.startswith("error")]
    if failed:
        logger.error("boot services with errors: %s", ", ".join(failed))
    return {"success": True, "services": list(results.keys()), "results": results, "failed": failed}
