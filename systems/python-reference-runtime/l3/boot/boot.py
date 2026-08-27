"""Boot sequence — Agent OS kernel startup and initialization, extensible via boot step registry.

Boot flow:
  1. Load constitution
  2. Initialize all kernel services
  3. Create Cell(s) with 3 Peer Agents
  4. Register agents with scheduler, IPC bus, ACB, identity
  5. Start heartbeat monitoring
  6. Start L3 coordinator
  7. Cell is ready to receive cards

Each Cell runs 3 Peer Agent terminals (A/B/C) + dynamic Scout pool.

Extending boot:
  from l3.boot.boot import register_boot_step
  register_boot_step("my_step", my_fn, depends_on=["init_services"])
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from l1.kernel.lifecycle import LifecycleState, get_lifecycle, transition
from l1.kernel.params.agent import DEFAULT_CELL_ID, TERRITORY_PATHS
from l1.kernel.params.system import PERSIST_AUTO, PERSIST_INTERVAL

from .boot_registry import (
    exec_step_with_timeout,
    lock_registry,
    register_boot_step,
    resolve_boot_order,
)
from .boot_steps import (  # noqa: F401 — re-export for tests / external callers
    _create_cell,
    _default_constitution,
    _init_discovery,
    _init_kernel_and_vfs,
    _init_memory_and_archive,
    _init_record_center,
    _init_services,
    _init_shells,
    _init_skills_and_network,
    _init_system_bus,
    _load_config,
    _load_constitution,
    _load_dvg,
    _load_tools,
    _post_boot_health_check,
    _prepare_layout,
    _register_event_schema,
)

logger = logging.getLogger(__name__)

# ── Boot state (not part of BootStep registry) ──
_BOOT_STEPS: list[str] = []
_BOOT_STARTED: float = 0.0
_BOOT_RESULT: dict | None = None

WIRED_KERNEL_OS: bool = False


def reset_boot_state() -> None:
    """Reset module-level boot state (for testing / retry).

    Clears the recorded step list, start timestamp and boot result so a fresh
    ``boot()`` run starts from a clean slate.
    """
    global _BOOT_STEPS, _BOOT_STARTED, _BOOT_RESULT
    _BOOT_STEPS = []
    _BOOT_STARTED = 0.0
    _BOOT_RESULT = None


def wire_kernel_os() -> None:
    """Register service-layer callbacks with the kernel OS.

    Idempotent — only wires once even if called multiple times.
    """
    global WIRED_KERNEL_OS
    if WIRED_KERNEL_OS:
        return
    try:
        from l1.kernel.os import get_os
        from l3.agent_terminal import reset_terminals
        from l3.cell import reset_cells

        from .lifecycle import shutdown as _lifecycle_shutdown

        osys = get_os()
        osys.register_boot_handler(boot)
        osys.register_shutdown_handler(_lifecycle_shutdown)
        osys.register_terminal_reset(reset_terminals)
        osys.register_cell_reset(reset_cells)
        WIRED_KERNEL_OS = True
    except Exception as e:
        logger.warning("kernel OS wiring skipped: %s", e)


def _enter_booting_state() -> None:
    """Transition to the BOOTING lifecycle state (non-fatal)."""
    try:
        if not transition(LifecycleState.BOOTING):
            logger.warning("boot: cannot enter BOOTING from %s", get_lifecycle().state().value)
    except Exception as e:
        logger.warning("boot: lifecycle transition failed: %s", e)


def _reset_singletons_on_retry() -> None:
    """Reset singletons first if the previous boot failed (retry safety)."""
    if _BOOT_RESULT and not _BOOT_RESULT.get("success"):
        logger.warning("previous boot failed — resetting singletons for retry")
        try:
            from .lifecycle import reset_all_singletons

            reset_all_singletons()
        except Exception:
            logger.warning("singleton reset unavailable, proceeding anyway")


def _wire_error_capture() -> None:
    """Bridge L1 PraxisError into the L3 ErrorBus (idempotent, early)."""
    try:
        from l1.kernel.errors import set_error_capture_handler

        def _kernel_error_handler(message: str, error_code: str, cause: Exception | None, context: dict | None) -> None:
            """Forward a kernel PraxisError into the L3 ErrorBus."""
            try:
                from l3.error_bus import capture

                capture(message=message, error_code=error_code, component="kernel", exc=cause, context=context or {})
            except Exception as e:
                logger.debug("boot: error capture bridge failed: %s", e)

        set_error_capture_handler(_kernel_error_handler)
        _BOOT_STEPS.append("error_capture_wiring")
    except Exception as e:
        logger.warning("boot: error capture wiring failed: %s", e)


def _wire_default_ports() -> None:
    """Register default port adapters early so cfg_language can switch locale."""
    try:
        from .wiring import wire_defaults

        wire_defaults()
        _BOOT_STEPS.append("wire_defaults")
    except Exception as e:
        logger.warning("boot wiring: %s", e)


def _run_bootstrap(interactive: bool) -> None:
    """Run the first-boot bootstrap wizard when needed."""
    try:
        from l3.config.bootstrap import needs_bootstrap, run_bootstrap

        if needs_bootstrap():
            logger.info("first boot detected — running bootstrap wizard")
            br = run_bootstrap(interactive=interactive)
            _BOOT_STEPS.append("bootstrap")
            if not br.get("success"):
                logger.warning("bootstrap incomplete: %s", br.get("error", ""))
    except Exception as e:
        from l3.error_bus import capture

        capture("bootstrap check failed", exc=e, component="kernel")
        logger.warning("bootstrap check: %s", e)


def _run_install_check() -> None:
    """Run the lifecycle install check (migrations + seed)."""
    try:
        lc = get_lifecycle()
        lc.load()
        if lc.should_install():
            from .install import install

            install()
            _BOOT_STEPS.append("install")
    except Exception as e:
        from l3.error_bus import capture

        capture("install check failed", exc=e, component="kernel")
        logger.warning("boot install check: %s", e)


def _register_shutdown_handler() -> None:
    """Register the atexit + signal shutdown handler so state is always saved."""
    try:
        from .lifecycle import register_shutdown_handler

        register_shutdown_handler()
        _BOOT_STEPS.append("shutdown_handler")
    except Exception as e:
        from l3.error_bus import capture

        capture("shutdown handler failed", exc=e, component="kernel")
        logger.warning("boot shutdown handler: %s", e)


def _restore_previous_state() -> None:
    """Restore previous kernel state if available."""
    try:
        from l1.kernel.persist import restore

        r = restore()
        if r.get("success"):
            _BOOT_STEPS.append("restored")
            logger.info("restored kernel state: %s processes, %s devices", r.get("processes", 0), r.get("devices", 0))
    except Exception as e:
        logger.warning("boot restore: %s", e)


def _auto_save_loop() -> None:
    """Periodic kernel state save (daemon thread target)."""
    while True:
        time.sleep(PERSIST_INTERVAL)
        try:
            from l1.kernel.persist import save

            save()
        except Exception as e:
            logger.warning("auto-save failed: %s", e)


def _start_auto_save() -> None:
    """Start the auto-save background thread if enabled."""
    if not PERSIST_AUTO:
        return
    t = threading.Thread(target=_auto_save_loop, daemon=True, name="persist")
    t.start()
    logger.info("auto-save started (every %.0fs)", PERSIST_INTERVAL)


def _resolve_agent_config(
    agent_config: list[tuple[str, str, list[str]]] | None,
) -> list[tuple[str, str, list[str]]]:
    """Load agent config from memories, else derive from territory paths."""
    if agent_config is None:
        try:
            from l3.memory.memory_init import init_from_memories

            m = init_from_memories()
            if m.get("loaded"):
                agent_config = m["agent_config"]
                _BOOT_STEPS.append("snapshot_restore")
                logger.info("boot from memories: %d agents from %s", len(agent_config), m.get("source", "?"))
        except Exception as e:
            logger.warning("memory init skipped: %s", e)

    if agent_config is None:
        # Generate agent config from territory paths (roles from constitution)
        agent_config = [(role, role, list(paths)) for role, paths in TERRITORY_PATHS.items()][:3]
    return agent_config


def _early_l2_load() -> None:
    """Push praxis.yaml overrides into SettingsCenter before the DAG runs.

    Only load + flatten here (no handler side effects); the full apply
    (start_api, device registration, etc.) happens once in load_config.
    """
    try:
        from l3.config.config_loader import load as _early_load
        from l3.config.settings_center import SettingsCenter
        from l3.config.settings_center import get_center as _sc

        _ec = _early_load()
        if _ec.get("success") and _ec.get("data"):
            _sc().load_l2(SettingsCenter._flatten(_ec["data"]))
    except Exception as e:
        logger.warning("boot early L2 load failed: %s", e)


def _execute_boot_steps(order: list[str]) -> tuple[dict, bool]:
    """Run each boot step in order; returns (results, success)."""
    from .boot_registry import _boot_registry

    results: dict[str, Any] = {}
    success = True
    for name in order:
        step = _boot_registry.get(name)
        if not step:
            continue
        try:
            # Emit boot step started event
            try:
                from l3.bus.monitor_bus import MonitorEvent
                from l3.bus.monitor_bus import get_bus as _mb

                _mb().emit(
                    MonitorEvent(
                        type="boot.step", source="boot", severity="info", message=f"step:{name} status:running"
                    )
                )
            except Exception:
                logger.debug("boot: boot step event emit failed")
            r = exec_step_with_timeout(step.fn)
            results[name] = r
            _BOOT_STEPS.append(name)
            if not r.get("success", True):
                logger.error("boot step failed: %s — %s", name, r.get("error", ""))
                success = False
                break
        except Exception as e:
            from l3.error_bus import capture

            capture(f"boot step {name} failed", exc=e, component="kernel")
            results[name] = {"success": False, "error": str(e)}
            success = False
            break
    return results, success


def _finalize_boot(
    success: bool, elapsed: float, agent_config: list[tuple[str, str, list[str]]], results: dict
) -> dict:
    """Assemble the boot result, snapshot, health check, event, and lifecycle transition."""
    global _BOOT_RESULT

    cell_result = results.get("create_cell", {})
    _BOOT_RESULT = {
        "success": success,
        "elapsed": round(elapsed, 3),
        "steps": list(_BOOT_STEPS),
        "results": results,
        "agent_count": len(agent_config),
        "cell_id": cell_result.get("cell_id", DEFAULT_CELL_ID),
        "agents": cell_result.get("agents", []),
    }
    # Save boot snapshot to memories so next restart knows what was running
    if success and agent_config:
        try:
            from l3.memory.memory_init import save_boot_snapshot

            path = save_boot_snapshot(agent_config)
            if path:
                _BOOT_RESULT["snapshot"] = path
        except Exception as e:
            logger.warning("boot snapshot save failed: %s", e)

    # Post-boot health check
    if success:
        try:
            _BOOT_RESULT["health"] = _post_boot_health_check()
        except Exception as e:
            logger.warning("health check failed: %s", e)

    # Emit boot complete event
    try:
        from l3.bus.monitor_bus import MonitorEvent
        from l3.bus.monitor_bus import get_bus as _mb2

        _mb2().emit(
            MonitorEvent(
                type="boot.complete",
                source="boot",
                severity="info",
                message=f"boot {'OK' if success else 'FAILED'} in {elapsed:.2f}s",
            )
        )
    except Exception:
        logger.debug("boot: boot complete event emit failed")

    # Lifecycle state transition
    try:
        lc = get_lifecycle()
        if success:
            lc.record_boot_success()
            transition(LifecycleState.ACTIVE)
        else:
            lc.record_boot_failure()
            transition(LifecycleState.CRASHED)
    except Exception as e:
        logger.warning("lifecycle transition failed: %s", e)

    logger.info("boot %s in %.2fs: %s", "OK" if success else "FAILED", elapsed, _BOOT_STEPS)
    return _BOOT_RESULT


def boot(agent_config: list[tuple[str, str, list[str]]] | None = None, interactive: bool = True) -> dict:
    """Full kernel boot sequence.

    Args:
        agent_config: list of (agent_id, role, territory) tuples.
        interactive: If True, runs bootstrap wizard on first boot.
    """
    global _BOOT_STARTED, _BOOT_RESULT

    # Lifecycle: enter BOOTING state + retry safety (reset singletons first)
    _enter_booting_state()
    _reset_singletons_on_retry()

    wire_kernel_os()

    # Bridge L1 PraxisError → L3 ErrorBus. Registered early so any kernel
    # error raised during boot is captured (idempotent; safe to re-register).
    _wire_error_capture()

    # Register default port adapters (i18n, worker, channel, event_bus, ...)
    # early so cfg_language (load_config step) can switch the active locale
    # and other services can resolve ports instead of relying on lazy fallbacks.
    _wire_default_ports()

    _BOOT_STARTED = time.time()
    _BOOT_STEPS.clear()

    _run_bootstrap(interactive)
    _run_install_check()
    _register_shutdown_handler()
    _restore_previous_state()
    _start_auto_save()

    resolved_config = _resolve_agent_config(agent_config)
    _early_l2_load()

    # Reset+register: boot_registry maintains its own lock/state
    from .boot_registry import reset_registry as _reset_boot_registry

    _reset_boot_registry()
    _register_default_boot_steps(resolved_config)
    lock_registry()

    order = resolve_boot_order()
    results, success = _execute_boot_steps(order)

    elapsed = time.time() - _BOOT_STARTED
    return _finalize_boot(success, elapsed, resolved_config, results)


def _register_default_boot_steps(agent_config: list | None) -> None:
    """Register all built-in boot steps via the extensible registry."""
    # prepare_layout runs first: every runtime dir must exist before any
    # service/step writes to the data dir (idempotent, no dependencies).
    register_boot_step("prepare_layout", _prepare_layout, depends_on=[])
    register_boot_step("load_constitution", _load_constitution, depends_on=["prepare_layout"])
    register_boot_step("init_discovery", _init_discovery, depends_on=["load_constitution"])
    register_boot_step("load_config", _load_config, depends_on=["init_discovery"])
    register_boot_step("init_shells", _init_shells, depends_on=["load_config"])
    register_boot_step("load_tools", _load_tools, depends_on=["load_config"])
    register_boot_step("load_dvg", _load_dvg, depends_on=["load_tools"])
    register_boot_step("init_system_bus", _init_system_bus, depends_on=["load_dvg"])
    register_boot_step("init_services", _init_services, depends_on=["init_system_bus"])
    register_boot_step("init_record_center", _init_record_center, depends_on=["init_services"])
    register_boot_step("register_event_schema", _register_event_schema, depends_on=["init_record_center"])
    register_boot_step("create_cell", lambda: _create_cell(agent_config), depends_on=["register_event_schema"])


def boot_status() -> dict:
    """Return the recorded boot result, or a not-booted error before the first boot."""
    if _BOOT_RESULT:
        return _BOOT_RESULT
    return {"success": False, "error": "not booted", "steps": _BOOT_STEPS}


def boot_summary() -> str:
    """Return a human-readable boot summary."""
    if not _BOOT_RESULT:
        return "Kernel not booted."
    r = _BOOT_RESULT
    status = "OK" if r["success"] else "FAILED"
    return f"Boot {status} in {r['elapsed']}s — {len(r['steps'])} steps: {' → '.join(r['steps'])}"
