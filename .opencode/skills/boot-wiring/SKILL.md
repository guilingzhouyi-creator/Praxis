---
name: boot-wiring
description: Use when writing or modifying Praxis boot wiring — boot.py 7-step bootstrap, boot_registry extensible steps, boot_steps/*, wiring.py port adapters, lifecycle factory reset, install.py, or boot error recovery.
---

## Overview

Architecture guide for the bootstrap system (`src/l3/boot/`). Boot is a 7-phase pipeline: port wiring first, then a registry-driven sequence of boot steps (each with declared dependencies), then finalize with health snapshot. Wiring.py is where all `*Port` adapters register — the single place `get_port(name)` consumers resolve against.

## Module Map

- **Orchestration**: `boot.py` — `boot()` entry, `_execute_boot_steps(order)` (registry lookup, per-step timeout via `exec_step_with_timeout`, failure halts the chain), `_finalize_boot` (result snapshot, health check, lifecycle transition), `boot_status()`/`boot_summary()`, `_reset_singletons_on_retry`
- **Step registry**: `boot_registry.py` — `register_boot_step(name, fn, depends_on=[])`; `boot_steps/` — `prepare_layout` (runtime dirs, idempotent, always first), `load_constitution`, `init_discovery`, `load_config`, `init_shells`, `load_tools`, `load_dvg`, `init_system_bus`, `init_services`, `init_record_center`, `create_cell` (+ `kernel.py`, `health.py`, `runtime.py`, `cell.py`, `services.py`, `tools.py`, `config.py`, `discovery.py`, `layout.py`, `shells.py`, `constitution.py`)
- **Port wiring**: `wiring.py` — `wire_defaults()` (stdlib-only adapters: i18n yaml, thread worker, ring channel, event bus, etc.), `wire_transport(adapter_name)` (tcp default), `wire_from_config(cfg)`, `reset_all()`
- **Lifecycle**: `lifecycle.py` — factory reset, singleton reset, disk wipe
- **Install**: `install.py` — install check + first-boot provisioning

## Core Conventions

- **Boot order is dependency-declared, not positional**: `register_boot_step(name, fn, depends_on=[...])`; `_execute_boot_steps` runs them in dependency-satisfying order and HALTS on first failure (result `{"success": False, "error": ...}`). New steps must declare dependencies and be idempotent.
- **Wiring is the ONLY adapter registration point**: `register_port("name", adapter)` in `wire_defaults()`/`wire_from_config()`; consumers resolve via `get_port(name)` from `src/l1/kernel/ports/`. Never bypass wiring by constructing a port consumer's adapter inline.
- **Failure recovery**: `_reset_singletons_on_retry` resets registered singletons before a retry; `_restore_previous_state` recovers the last known-good snapshot; error capture wired via `_wire_error_capture` (`capture()` on error_bus, component="kernel").
- **prepare_layout runs first**: every runtime dir must exist before any service/step writes to the data dir — new runtime paths must be provisioned there.
- **capability executor wiring**: boot is the ONLY place that wires the `invoke_capability` executor (boot_steps/tools.py) — never wire it elsewhere.
- **New services**: register their reset function in `tests/conftest.py` `_RESETS` (autouse fixture isolates tests); singleton scan (`scripts/py/scan-singletons.py`) keeps the list in sync.
- **Config flow**: boot reads three-layer config — params defaults ← `config/discovery/*.yaml` ← `config/praxis.yaml`.

## Tests

- `python -m pytest tests/ -k "boot or wiring" -x -q`
- `python -m pytest tests/infra/test_layer_imports.py -x -q` (boot wiring imports L4 adapters — cross-layer allowlist awareness)
