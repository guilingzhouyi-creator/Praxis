# L1 — Kernel Layer

The bare-metal kernel: what every upper layer builds on. 58 files /
17,128 lines; 1,119 constants across 9 `params/` modules.

## Responsibility boundary

- Owns process, memory, synchronization, events, security gates, and the
  port abstraction — **nothing above L1 may be imported by L1**.
- Upper layers reach kernel facilities only through: syscall-style module
  imports, the event bus, port adapters, and `params/*` constants.

## Core modules

| Module | Role |
|--------|------|
| `process.py` | ProcessTable + PCB (agents are processes: ring, state, identity, audit) |
| `sync.py` | Mutex / Semaphore / Barrier / RWLock (RLock-reentrant) |
| `event.py` | EventBus: typed `SignalType` (20 members incl. card/approval flow), async dispatch via thread pool, string-event registry |
| `constitution.py` | Constitutional rules engine (highest authority; `.praxis-rules.md`) |
| `gatechain.py` | G1–G5 tool authorization chain (whitelist/identity/territory/escalation/composite) + stagnation callback |
| `ports/` | `*Port(ABC)` abstractions (package), including `InputActivityPort`, plus `register_port`/`get_port` registry |
| `allocator.py` | Token allocation + GC |
| `vfs.py` / `registry.py` / `registry_base` | Virtual FS, system registry |
| `os.py` | Lifecycle: boot/shutdown/restart/watchdog |
| `ipc.py` / `net.py` / `net_transport.py` | IPC channel, cross-cell mesh, TLS transport |
| `process.py` audit, `reputation.py` trust, `swapper.py` ring swapping, `interrupt.py` IRQ table |
| `skill.py` | SkillManager (load/create/evolve/usage, write-gated) |
| `identity_binding.py` | Per-Cell role bindings (write-gated, revisioned durable registry) |
| `prompts.py` | Prompt registry (L3A system/parse templates, verification culture, versioned overrides/rollback) |
| `params/*` | 1,067 compile-time constants (kernel/allocator/sync/gatechain/agent/tool/api/system/…) |

## Core mechanisms

### Event bus (async dispatch)

```
emit_signal(type, sender, target, data) → Signal → history + thread-pool dispatch
on(type, cb) / on_any(cb) / on_event(str, cb)   ← SSE/WS bridges subscribe on_any
String events auto-register (emit_event) — extensible without enum changes.
emit_signal resolves static enum members first, then falls back to dynamic
registration (register_signal_type) — unknown names never raise KeyError.
```

### GateChain (G1–G5)

```
G1 whitelist → G2 identity (process table) → G3 territory+risk → G4 escalation → G5 composite
BLOCK stops tool execution; WARN passes with audit. Ledger records every check.
```

**Fail-closed G1 (W2.3):** an empty whitelist now BLOCKs instead of WARN
(`GATECHAIN_REQUIRE_WHITELIST`, default True); boot populates it from the tool
registry (`boot_steps/tools.py::_register_g1_whitelist`).

**Interactive principals (W1.2):** boundary-authenticated callers (local L2
shell, API/MCP behind closed-by-default auth) pass G2 without a kernel PCB via
`interactive=True`; G1/G3/G4/G5 still apply.

### Port abstraction

```python
class AuthPort(ABC): issue_token / verify_token / revoke_token / refresh_token
class WebSocketPort(ABC): upgrade / recv(conn) / send(conn) / close(conn) / broadcast
class RpcServerPort(ABC): register_handler / call / notify
class FilesystemPort(ABC): read / write / list_tree / watch
class ProcessPort(ABC): run / run_args (ProcessOptions) → ProcessResult
class CandidateLedgerPort(ABC): list / validate / publish / activate / retire
class InputActivityPort(ABC): start / stop / aggregate snapshot
+ TransportPort, ChannelPort, EventBusPort, WorkerPort, I18nPort,
  CardRegistryPort, MonitorBusPort, LLMPort, StoragePort, LockPort
```

Adapters self-register (`register_port("auth", svc)`) at service init or
boot wiring; consumers resolve via `get_port(name)` — **duck-typed, so a
language-agnostic kernel can swap adapters without import changes**. One-shot
command callers use `get_process_port()`, which resolves the registered
`"process"` adapter or a controlled stdlib fallback before boot. The registry
is `RLock`-guarded. `WorkerPort.submit_result()` returns a
`TaskHandle` (future-like) so a computed value crosses the worker boundary —
the completion half missing from fire-and-forget `submit()`.

### Rust-sink readiness (per `docs/roadmaps/frontend-kernel-roadmap.md`)

> **Boundary baseline**: `docs/roadmaps/kernel-boundary-audit.md` fixes which L1
> surfaces a Rust sink may replace (mechanism only) and which must be sealed
> first in Python — single execution authority (invoke-capability gate), a
> populated G1 whitelist, closed-by-default auth, and the B1/B2/B3 bypass paths.

The roadmap sinks hot modules to Rust **one at a time, interface unchanged,
via the port**. What is swappable vs. what a Rust sink replaces wholesale:

| Surface | Seam | Notes |
|---|---|---|
| Shell/command exec | `ProcessPort` (`get_process_port()`) | `run`/`run_args` take explicit `ProcessOptions` and return `ProcessResult`; boot adapter or controlled pre-boot fallback |
| Thread pool | `WorkerPort` + `TaskHandle` | `ThreadPoolWorker`; result contract complete |
| Filesystem / storage | `FilesystemPort` / `StoragePort` | both resolve via `get_port` |
| R4 candidate ledger | `CandidateLedgerPort` | typed primitive-only evidence, snapshots, status, and lifecycle results; memory and API callers resolve the port |
| Input activity | `InputActivityPort` | aggregate `start`/`stop`/`snapshot` seam; a hardware provider can move to Rust while privacy policy stays in L3 |
| Value types | `ProcessResult` / `ProcessOptions` / `Result` / `Event` | frozen dataclasses — no interpreter object crosses the boundary; `error_kind` distinguishes adapter errors from child exit codes |
| `sync.py` primitives, core `EventBus` | **intentionally concrete** | the bottom layer a Rust kernel *replaces wholesale*, not wraps — `LockPort` exists for adapter-swappable higher-level uses; routing every kernel `Lock` through it adds indirection with no current benefit (M3: serial P≈0) |

`ProcessPort` is deliberately limited to bounded, non-interactive commands.
Interactive shell sessions, LSP stdio servers, and supervised daemon processes
hold Python `Popen` handles with live pipes and lifecycle callbacks; they are
Python-only runtime implementations, not an FFI-clean port surface.

`ProcessResult.error_kind` is empty for every command that actually started,
including a child that exits with a negative signal code. Adapter failures use
`not_found` or `execution`; timeouts set `timed_out`. Callers must branch on
these structured fields rather than inferring failures from a synthetic return
code.

The event bus tracks its own in-flight counter (no CPython
`ThreadPoolExecutor` private access), so a non-CPython worker backend drops in
cleanly.

### Engineering-debug boundary

The marker-gated engineering mode is an L3 policy owned by
`l3.tool_system.engineering_debug`; L1 does not inspect marker files or decide
whether a caller is a developer. L1 supplies two language-neutral primitives
used by that policy:

- `prompts.py` owns the built-in/config prompt registry, runtime overlay
  mutation, bounded version snapshots, and rollback. Authorization and the
  production-versus-engineering decision remain above L1.
- `InputActivityPort` and `InputActivitySnapshot` define an aggregate-only
  provider contract. Implementations expose `start`, `stop`, and `snapshot`
  but never need to transfer key contents, pointer coordinates, or interpreter
  objects across the boundary. The default L3 provider is no-op when the host
  has no permission or hardware adapter.

Engineering transitions are recorded by L3 through the event bus and
reference channel; this keeps audit and observability side effects out of the
kernel's execution gates.

### Identity-binding persistence

`IdentityBindingManager` captures an immutable binding snapshot and local
revision while holding its registry lock. A state-path lock then serializes a
read/merge/write transaction across manager instances: only the committed
bind, unbind, or clear delta is applied to the current durable JSON state.
Each replacement uses a uniquely named sibling temporary file, so concurrent
writers never share a `.tmp` path and unrelated bindings remain intact.

## Key constants (params)

- `PROCESS_DEFAULT_RING`, `PROCESS_AUDIT_MAX`, `PROCESS_TABLE_MAX`
- `EVENT_BUS_WORKERS`, `EVENT_BUS_MAX_QUEUED`
- `GATECHAIN_*` risk/repeat thresholds
- `AUTH_SIGN_KEY_BYTES`, `AUTH_TOKEN_TTL_SECONDS`, `API_PAGE_MAX_LIMIT`,
  `API_WS_PORT`, `RPC_SERVER_PORT`
- `LOG_TRUNC_*`, `HASH_TRUNC_*` (truncation discipline — never inline)
- `ENGINEERING_DEBUG_*` marker, logging, input, recheck, and prompt-size defaults

## Config surface

- `config/praxis.yaml`: kernel/gatechain/constitution sections
- SettingsCenter keys: `prompt.inject.*`, `user_profile.enabled`,
  `memory.graph.enabled`, `memory.mer.enabled`, `engineering_debug.*`
