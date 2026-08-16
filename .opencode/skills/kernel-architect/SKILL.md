---
name: kernel-architect
description: Use when writing or modifying Praxis L1 kernel code — syscall surfaces, params constants, sync/event primitives, constitution, gatechain, capability invocation, VFS/IPC, ports abstraction, or params governance.
---

## Overview

Architecture guide for the L1 kernel (`src/l1/kernel/`, ~58 files, 17k lines). The bare-metal layer every upper layer builds on — nothing above L1 may be imported by L1 (one-way dependency, enforced by `tests/infra/test_layer_imports.py`). Upper layers reach kernel facilities only through: syscall-style module imports, the event bus, port adapters, and `params/*` constants.

## Module Map

- **Process**: `process.py` — ProcessTable + PCB (agents are processes: ring, state, identity, audit)
- **Sync**: `sync.py` — Mutex/Semaphore/Barrier/RWLock (plain `threading.Lock` for flat critical sections; `threading.RLock` where the holder may re-acquire, e.g. event/worker/registry)
- **Events**: `event.py` — EventBus: typed `SignalType` (20 members), async dispatch via thread pool, string-event registry; `emit_event` auto-registers string types
- **Authority**: `constitution.py` (rules engine, `.praxis-rules.md`), `gatechain.py` (G1–G5 tool authorization), `capability.py` (single execution authority, `invoke_capability`), `identity_binding.py` (per-Cell role bindings, write-gated)
- **Resources**: `allocator.py` (tokens+GC), `resource.py`, `vfs.py` (virtual FS), `registry.py`/`registry_base.py`, `swapper.py` (ring swapping), `reputation.py` (trust)
- **Lifecycle**: `os.py` (boot/shutdown/restart/watchdog), `lifecycle.py`
- **Communication**: `ipc.py`, `net.py`, `net_transport.py` (TLS), `channel_ring.py`, `bus.py`
- **Config surface**: `params/` (1,119 compile-time constants, 9 modules), `settings.py` (DEFAULTS registry), `paths.py`, `prompts.py` (prompt registry — prompt templates are data, not params), `discovery.py`, `platform.py` (OS abstractions)
- **Ports**: `ports/` — 15 `*Port(ABC)` abstractions (core/service/storage/lock/types/registry packages), adapters self-register via `register_port(name, svc)`, consumers resolve via `get_port(name)` (duck-typed)

## Core Conventions

- **All magic numbers go in `src/l1/kernel/params/`** — never hardcode in implementation files. `tests/infra/test_params_compliance.py` (strict mode) enforces it.
- **New kernel modules MUST be exported** in `kernel/__init__.py` `__all__`; new config items register defaults in `kernel/settings.py` `DEFAULTS`.
- **GateChain**: G1 whitelist → G2 identity → G3 territory+risk → G4 escalation → G5 composite; BLOCK stops execution, WARN passes with audit. Empty whitelist fail-closes (`GATECHAIN_REQUIRE_WHITELIST`, boot populates it from tool registry).
- **capability.py is the single execution authority**: boot is the ONLY place that wires it (`boot_steps/tools.py::_register_capability_executor` → `invoke_gated`); kernel never imports L3; an unwired executor denies every call (fail-closed).
- **Ports are duck-typed adapters**: `register_port()`/`get_port()` in `src/l3/boot/wiring.py` wire them at boot; a language-agnostic kernel can swap adapters without import changes. `ProcessPort` is limited to bounded non-interactive commands — interactive shells/LSP hold Python `Popen` handles (not FFI-clean).
- **Truncation**: use `LOG_TRUNC_*` / `HASH_TRUNC_*` from params, never raw `[:40]` slices.
- **Event bus**: `emit_signal` resolves static enum members first, falls back to dynamic registration — unknown names never raise KeyError. `on_any(cb)` used by SSE/WS bridges.
- **Unified trace_id**: one trace id flows request → agent → tool → error via error_bus; propagate it, never mint new ids.

## Gates

- `python -m pytest tests/infra/test_layer_imports.py -x -q` (layer rules; new cross-layer imports must be allowlisted there)
- `python -m pytest tests/infra/test_params_compliance.py -x -q` (strict params compliance)
- Kernel tests: `python -m pytest tests/l1/test_kernel.py -x -q`
