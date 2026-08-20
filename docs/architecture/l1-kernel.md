# L1 — Kernel Layer

The bare-metal kernel: what every upper layer builds on. 68 files /
17,919 lines; 1,175 constants across 8 `params/` modules (mechanism-only —
see *Kernel surface boundary* below).

## Responsibility boundary

- Owns process, memory, synchronization, events, security gates, and the
  port abstraction — **nothing above L1 may be imported by L1**.
- Upper layers reach kernel facilities only through: syscall-style module
  imports, the event bus, port adapters, and `params/*` constants.

## Core modules

| Module | Role |
|--------|------|
| `process.py` | ProcessTable + PCB (agents are processes: ring, state, identity, audit) |
| `sync.py` | Mutex / Semaphore / Barrier / RWLock (RLock-reentrant; RWLock write depth is explicit) |
| `event.py` | EventBus: typed `SignalType` (20 members incl. card/approval flow), async dispatch via thread pool, string-event registry |
| `constitution.py` | Constitutional rules engine (highest authority; `.praxis-rules.md`) |
| `gatechain.py` | G1–G5 tool authorization chain (whitelist/identity/territory/escalation/composite) + stagnation callback |
| `ports/` | `*Port(ABC)` abstractions (package) — mechanism-only after WS5.1: I/O, process, trace, observability, evidence, and dependency-graph ports + `register_port`/`get_port` registry; domain ports moved to `l3/ports.py` / `l4/ports.py` |
| `allocator.py` | Token allocation + GC |
| `vfs.py` / `registry.py` / `registry_base` | Virtual FS, system registry |
| `os.py` | Lifecycle: boot/shutdown/restart/watchdog |
| `lifecycle.py` / `versioning.py` / `migration.py` | Persistent lifecycle record, schema versions, ordered install migrations |
| `ipc.py` / `net.py` / `net_transport.py` | IPC channel, cross-cell mesh, TLS transport |
| `process.py` audit, `reputation.py` trust, `swapper.py` ring swapping, `interrupt.py` IRQ table |
| `skill.py` | SkillManager (load/create/evolve/usage, write-gated) |
| `model_registry.py` / `commands.py` | Transition shims (WS5.2/5.3): implementations moved to `l4/llm/model_registry.py` / `l2/commands.py` |
| `identity_binding.py` | Per-Cell role bindings (write-gated, revisioned durable registry) |
| `prompts.py` | Transition shim (WS5.3): implementation moved to `l3/agent/prompts.py`; kernel keeps the import path for compat |
| `params/*` | 1,175 compile-time constants — mechanism-only after WS5.4 (kernel/allocator/sync/gatechain/tool/system); business constants live in `l3/params.py` (agent/card-gate/review/scout) and `l4/params.py` (API/eval/diff/security-gate) |


## Kernel surface boundary (Rust readiness)

The kernel’s semantic surface is frozen for the Rust rewrite (`l1_kernel_rs`):
security/control invariants and explicitly retained wire fields are evidence;
Python class layout and user-data formats are not migration requirements.

The staged Rust build boundary lives in `crates/l1-kernel-rs/`. Its primitive
value contracts are mirrored and isolated mechanism candidates now cover
sync/process/event/channel/allocator/worker, lock IPC, journal, bounded audit,
capability-authority, G1-G5 gatechain, Constitution rule/evaluation shapes,
provider-neutral VFS mount/cache mechanics, platform value/command descriptions,
deployment path derivation, lifecycle FSM, schema versioning, ordered migration
runner, pure load-adaptive control law, metadata-only registry base and summary,
deterministic device bookkeeping, explicit health-result aggregation, memory-ring swap planning, and tool-call fingerprint chaining, but it remains candidate-only until a
fixed-work performance evidence, semantic invariant vectors, and a
cutover/recovery decision; the preflight branch keeps the Python kernel as its
runtime implementation until the independent Rust build reaches R4/R5.

The Rust-first R1 substrate now provides generation-tagged process handles,
deterministic shard planning, and allocation-free atomic queue metrics. These
are ownership and measurement primitives only; they do not start scheduling,
replace ProcessTable storage, wire boot, or grant runtime authority.

The Rust `benchmark` candidate defines the fixed-work R2 report shape and
rejects incomplete work, unknown worker counts, duplicate/out-of-range rounds,
zero-duration samples, invalid p95/p99 ordering, and unsupported schema
versions. Schema v2 records p95/p99 tail latency, aggregate queue/lock waits,
and rejected work. Throughput is derived from fixed completed work and elapsed
time via `BenchmarkSample::throughput_ops_per_sec`; the candidate records
evidence only.

The Rust `benchmark_runner` candidate measures a fixed total through a bounded
typed queue for each worker/round pair and drains the queue before emitting a
complete v2 report. It is a contention/stress smoke only; it does not start
scheduling, replace ProcessTable storage, wire boot, or grant runtime
authority.

`BenchmarkEvidence` is the versioned export envelope for this report. It binds
the complete worker/round matrix to platform, architecture, runtime, source
revision, and runner metadata and rejects invalid or incomplete JSON on both
construction and ingestion. `make rust-benchmark` emits one release-mode
evidence document; runtime attribution can be supplied through
`PRAXIS_RUST_RUNTIME`, `PRAXIS_GIT_REVISION`, and `PRAXIS_RUST_RUNNER`. The
runner still does not measure CPU or memory and does not replace the Python
reference baseline, so this output cannot by itself close R2.

The `state_queue` candidate gives each shard ownership of its slot map and
lifecycle transitions, and uses typed work items with fail-fast capacity
rejection. Queue length and accepted-but-not-completed metric depth remain
separate measurements; task scheduling, boot state, and runtime routing stay
outside the candidate.

The Rust `identity_binding` candidate closes the mechanism portion of the
per-Cell role registry: an injected write principal is checked fail-closed,
each Cell has a bounded role set, rebinds preserve the existing system-issued
identity ID, metadata revisions are monotonic, and snapshots are deterministic.
Prompt fragments and definitions, JSON persistence, EventBus notifications,
singleton ownership, and API/L2Shell policy remain adapter-owned. The Rust
candidate therefore gives the future kernel a typed metadata boundary without
making prompt content or Python state layout a compatibility requirement.
The shared `kernel_identity_binding_vectors.json` fixture covers only the
authorization and mutation lifecycle; prompt text, random UID bodies, and
persistence bytes remain deliberately outside the contract.

The Rust `network` candidate is limited to a caller-clocked `PeerBook`: it
validates peer endpoints, ignores self announces, reports a peer loss once,
evicts after a declared grace period, and returns deterministic health/list
snapshots. TCP/UDP discovery, TLS, sockets, EventBus events, card sync, and
message envelopes remain transport adapters. The shared
`kernel_peer_vectors.json` fixture covers the timeout, refresh, loss, and
eviction lifecycle without making wall-clock or wire bytes a Rust contract.

The Rust `boot` candidate is limited to declarative assembly metadata. Its
`BootPlan` validates names, rejects duplicate registrations unless an explicit
replacement is requested, locks before execution wiring, and resolves a
deterministic dependency-first order. Missing dependencies and cycles fail
closed. It does not execute boot callbacks, read settings, start threads,
change lifecycle state, or replace the Python boot registry. The shared
`kernel_boot_plan_vectors.json` fixture freezes only this ordering/error
boundary; Python's omission of missing dependencies remains a documented
reference behavior rather than a Rust requirement.

The Rust `state_layout` candidate starts the R4 state-ownership boundary. It
validates a versioned manifest for a fresh Rust state root, canonical relative
entries, and declared parent directories. Given explicit host observations it
returns `initialize`, `resume`, `recover`, `migrate`, or fail-closed `reject`.
It does not inspect the filesystem, create directories, import Python state,
or execute migration callbacks. The shared
`kernel_state_layout_vectors.json` fixture freezes only the manifest and
decision values; a future R4 adapter owns probes and side effects.

The Rust `ports` candidate translates the mechanism value surface and adapter
discovery metadata. `PortResult`, `Endpoint`, `Message`, and the
privacy-preserving `InputActivitySnapshot` are validated without I/O, while
`PortRegistry` provides deterministic registration order, duplicate rejection,
explicit replacement, and a pre-wiring lock. It does not instantiate provider
implementations or execute process, storage, transport, scheduler, worker, or
input activity operations. `kernel_port_vectors.json` freezes only these
values and metadata; provider side effects remain an R4 adapter concern.

The Rust `assembly` candidate composes the boot plan, fresh state manifest,
port metadata, and halted lifecycle into a deterministic `KernelAssembly`.
`crates/l1-kernel-rs/src/bin/rust-kernel.rs` is an independent entrypoint that
emits this snapshot as JSON with no Python import. The entrypoint does not read
configuration, create directories, run callbacks, or instantiate providers;
R4 filesystem initialization, versioned protocol serving, and recovery effects
remain to be implemented behind this seam.

- **Contract snapshot (W6.3)** — `docs/contracts/kernel-contract.json` is a versioned
  golden JSON of kernel modules / classes / functions / syscall registry, generated by
  `scripts/py/gen_kernel_contract.py` and drift-checked by
  `tests/infra/test_kernel_contract_snapshot.py`. The Rust side aligns item by item.
- **Mechanism/policy split (WS5)** — domain ports, prompts, commands, model registry,
  diff frames, and business params no longer live in the kernel namespace:
  `l3/ports.py` + `l4/ports.py` (ports), `l3/agent/prompts.py`, `l2/commands.py`,
  `l4/llm/model_registry.py`, `l4/sandbox/diff_frame.py`, `l3/params.py` + `l4/params.py`;
  kernel `ports/` and `params/` keep only mechanism.
- **Capability seam (W6.1)** — tool execution enters the kernel only via
  `invoke_capability()` → `invoke_gated` (fail-closed when no executor is wired);
  boot is the single wiring point.
- **Scheduler port (W6.2)** — `KernelSchedulerPort` in `kernel/ports/scheduler.py`,
  implemented by L3 `CentralScheduler`; the kernel syscall path notifies it.
- **Process FSM (WS3)** — `ProcessTable` drives READY/RUNNING/BLOCKED/ZOMBIE/STOPPED
  transitions and exposes kernel cancel + handle primitives; audit persists to the
  journal as `audit.syscall` (W4.1).
- **Discovery boundary** — the Rust `discovery` candidate mirrors the three-tier
  defaults/source/runtime registry, parsed section overrides, object shallow merge,
  scalar replacement, null-section default retention, and tool/service fallbacks.
  YAML parsing, directory scanning, logging, and boot registration remain Python
  adapter responsibilities.

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

**Verified identity for high rings (W2.4):** a non-interactive agent whose ring
is >= `GATECHAIN_REQUIRE_IDENTITY_RING` (default 2) MUST have a verified
identity (Ed25519 keypair) or G2 BLOCKs (was WARN); ring-1 keeps the legacy
WARN. The identity service (`l3/services/identity.py::mark_identity_verified`)
verifies agents at boot.

The Rust `reputation` candidate is limited to a policy-injected, thread-safe
score ledger for G5 inputs. It clamps finite values and applies task/review/
dispute deltas, but does not own singleton state, persistence, provider
updates, or GateChain routing.

The Rust `notify` candidate is a side-channel-only bounded buffer with
caller-supplied timestamps, newest-first reads, and explicit drop counters. It
does not emit EventBus signals or own SSE/WS/webhook delivery.

### invoke-capability syscall (W6.1)

```
boundary caller (L2 shell / API / MCP)
  → l1.kernel.invoke_capability(agent_id, name, args, interactive)
      → [unwired executor? fail-closed BLOCK + audit]
      → wired executor (boot adapter → L3 ToolPipeline)
      → kernel audit record (capability.invoke)
```

`src/l1/kernel/capability.py` owns the single execution authority: boot is the
ONLY place that wires it (`boot_steps/tools.py::_register_capability_executor`
connects it to `invoke_gated`), the kernel never imports L3, and an unwired
executor denies every call. This is the seam `l1_kernel_rs` replaces: swap the
boot adapter, no caller changes.

### Port abstraction

```python
class AuthPort(ABC): issue_token / verify_token / revoke_token / refresh_token
class WebSocketPort(ABC): upgrade / recv(conn) / send(conn) / close(conn) / broadcast
class RpcServerPort(ABC): register_handler / call / notify
class FilesystemPort(ABC): read / write / list_tree / watch
class ProcessPort(ABC): run / run_args (ProcessOptions) → ProcessResult
class CandidateLedgerPort(ABC): list / validate / publish / activate / retire
class InputActivityPort(ABC): start / stop / aggregate snapshot
class ObservabilityPort(ABC): emit_count / emit_duration
class EvidencePort(ABC): record_evidence → evidence id
class DependencyGraphPort(ABC): plan(nodes) → ordered node ids
class TracePort(ABC): scope(trace_id) → context manager
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
| Automation side channels | `ObservabilityPort` / `EvidencePort` / `DependencyGraphPort` / `TracePort` | build runners resolve stable ports; boot adapters may replace L3 metrics, evidence, DVG, and trace implementations without changing manifest/report consumers |
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

The Rust workspace currently contains isolated candidates for synchronization,
process lifecycle, EventBus delivery, JSON channels, allocator/resource
accounting, bounded WorkerPort execution, lock IPC, append-only journal
records, bounded audit, the single capability execution authority, the
pure G1-G5 gatechain, the pure Constitution rule evaluator, provider-neutral
VFS mount/cache mechanics, and SystemBus dependency planning. These are
build-only candidates; posture/approval/
reputation providers, socket transport, SQLite replay, the
named registry, adaptive worker control, real filesystem/system providers,
and runtime routing remain Python-owned in the preflight branch. The future
Rust-first build may own a redesigned implementation after its semantic
invariants, performance evidence, and clean cutover/recovery path are frozen.

The VFS candidate owns only the language-neutral mechanism: a bounded mount
table with longest-prefix lookup, ring/read-only authorization, virtual files,
and TTL-bounded provider-read cache invalidation. `read_from_provider` and
`list_from_provider` accept already-produced values; real OS I/O and `/proc`,
`/sys`, `/skills`, and `/dev` providers stay above L1. Non-virtual `read`,
`write`, `list_dir`, and `unlink` return `EADAPTER` rather than touching an
unmounted or direct OS path, preserving a fail-closed Rust boundary.

The shared policy fixture `tests/fixtures/kernel_policy_vectors.json` covers
the stable GateChain and Constitution block/pass branches in both languages.
It is a semantic baseline, not a runtime routing switch; Python provider and
side-effect behavior remains outside the fixture and is not automatically a
Rust compatibility requirement.

The lifecycle and schema candidates use
`tests/fixtures/kernel_lifecycle_vectors.json` and
`tests/fixtures/kernel_versioning_vectors.json` for deterministic Python/Rust
parity. Checkpoint bytes, timestamps, settings registration, and migration
side effects remain provider-owned; the Rust code only validates and transforms
primitive values.

The discovery candidate uses
`tests/fixtures/kernel_discovery_vectors.json` for deterministic registry
parity. It accepts an already parsed document and preserves Python's defaults,
source snapshots, object shallow merge, scalar replacement, null-section rule,
unknown-section ignore behavior, runtime overrides, and tool/service fallback
queries. It does not scan directories, parse YAML, emit logs, register boot
sources, or mutate the Python runtime registry.

The load-adaptive candidate uses
`tests/fixtures/kernel_load_adaptive_vectors.json` to freeze EWMA smoothing,
hysteresis, target-band hold, growth/shrink clamping, slow-task fast growth,
cooldown, and reset behavior. The timestamp is an explicit caller value so the
candidate performs no clock or thread-pool I/O; Python retains sampling,
`WorkerPort` mutation, adaptive enablement, and runtime worker ownership.

The schema candidate uses `tests/fixtures/kernel_schema_vectors.json` to freeze
owner-conflict rejection, same-owner idempotent updates, sorted snapshots,
membership checks, and reset. It does not load the L3 event catalog, emit
signals, or decide event ownership at boot; those remain Python-owned policy
and registration inputs.

The rule-descriptor candidate uses
`tests/fixtures/kernel_rule_descriptor_vectors.json` to freeze MUST/SHOULD/MAY
severity conversion, PASS/WARN/BLOCK results, descriptor metadata, sorted tags,
and explicit checker context. Callback closures are injected at the adapter
boundary; rule content, Markdown/SettingsCenter I/O, and Constitution policy
remain outside the candidate.

The registry-base candidate uses
`tests/fixtures/kernel_registry_base_vectors.json` to freeze declarative
descriptor defaults, duplicate rejection/overwrite policy, registration order,
category filtering, public serialization, and counters. Rust callbacks are
local adapter hooks only; Python handler closures, domain registries, source
discovery, and runtime routing remain outside the candidate.

The registry candidate uses `tests/fixtures/kernel_registry_vectors.json` to
freeze name-sorted opaque section snapshots and explicit summary aggregation
(healthy module count, process/device/syscall counts, and caller-supplied time).
It accepts JSON values and explicit counts only; section producers, singleton
queries, syscall discovery, clocks, and runtime registry ownership remain
Python adapter responsibilities.

The tool-chain candidate uses `tests/fixtures/kernel_tool_chain_vectors.json`
to freeze call-field normalization, HMAC-SHA256 truncation, the `GENESIS`
fallback, and root-first fingerprint-chain verification. Key provisioning,
call storage, trimming/re-rooting, and tool execution remain Python-owned; the
candidate has no runtime singleton or capability authority.

Rust parity tests for this boundary run as an integration test from
`crates/l1-kernel-rs/tests/contract_vectors.rs`; private mechanism tests remain
colocated with their Rust modules so they can assert internal invariants.

The identity-UID candidate uses
`tests/fixtures/kernel_identity_uid_vectors.json` to freeze the readable prefix,
bounded body length, collision tracking, retry budget, reset, and validation
shape. Entropy candidates are explicit inputs; Python `secrets`, persisted
bindings, and identity issuance authority remain outside Rust.

The device candidate uses `tests/fixtures/kernel_device_vectors.json` to freeze
explicit device records, sliding-window rate checks, strict degraded/down
thresholds, call counters, health updates, summaries, and aggregate stats.
SettingsCenter defaults, external connections, system time, health threads, and
provider calls remain Python adapter responsibilities.

The SystemBus candidate uses `tests/fixtures/kernel_bus_vectors.json` to freeze
component metadata defaults, in-place duplicate replacement, parent-available
dependency filtering, stable topological ordering, cycle rejection, and state
labels. It consumes only already-resolved metadata and dependency names;
callbacks, event routing, child-bus mounting, health/stats providers, logging,
and runtime lifecycle ownership remain Python adapter responsibilities.

The ResourceLimiter candidate uses `tests/fixtures/kernel_resource_vectors.json`
to freeze injected profile values, fallback lookup, signed check/release costs,
usage and all-usage snapshots, unknown-resource handling, and cleanup. Python
role/profile discovery remains the adapter input; allocator OOM reclamation,
interrupt delivery, process termination, worker ownership, and durable swap
persistence remain outside this value candidate.

The health candidate uses `tests/fixtures/kernel_health_vectors.json` to freeze
explicit subsystem-result aggregation, `DOWN`/`DEGRADED`/`OK` precedence,
status counts, subsystem retention, and elapsed-time rounding. Module imports,
clocks, singleton probes, logging, and runtime provider checks remain Python
adapter responsibilities; the candidate does not invoke `safe_system_check()`
or own health authority.

The swapper candidate uses `tests/fixtures/kernel_swapper_vectors.json` to
freeze importance-based ring routing, expired short-ring compaction filters,
and explicit pressure action flags. It consumes no MemoryService objects,
allocator samples, clocks, worker threads, or persistence; the Python
`Swapper` remains the runtime owner of all mutations and scheduling.

The platform candidate uses
`tests/fixtures/kernel_platform_vectors.json` for deterministic POSIX/Windows
shell and grep command construction, URL joining, temporary-directory
derivation, and TCP endpoint parsing. It does not perform subprocess, directory,
filesystem, or socket I/O; the Python platform adapter retains those effects.

The paths candidate uses
`tests/fixtures/kernel_paths_vectors.json` for deployment-mode and child-path
derivation. `PathInputs` carries host/environment values explicitly; Rust does
not inspect environment or home directories, create layout directories, or
alter the Python singleton in the preflight branch; the future Rust-first
build may use a fresh state root after its cutover/recovery contract is
approved.

The territory candidate uses
`tests/fixtures/kernel_territory_vectors.json` for lexical, component-aware
subtree checks. Relative path resolution accepts an explicit working directory;
the candidate never reads the process working directory, follows symlinks, or
touches the filesystem. GateChain and Constitution continue to call the same
boundary helper while Python retains the runtime adapter and policy authority.

The interrupt candidate uses
`tests/fixtures/kernel_interrupt_vectors.json` for the five stable IRQ kinds,
per-kind sequence counters, empty-payload normalization, and bounded recent
history. It records values behind a mutex but does not execute callbacks, emit
signals, write the event journal, or terminate processes; those dispatch and
replay effects remain Python-owned.

The errors candidate uses
`tests/fixtures/kernel_error_vectors.json` for the built-in error catalog,
unknown-code fallback, Python-compatible failure responses, bounded causes,
and explicit trace-id attachment. Locale lookup, ErrorBus capture, stack/source
inspection, and log persistence remain outside the candidate.

The synchronization candidate uses the shared value fixture
`tests/fixtures/kernel_value_vectors.json` for RWLock write reentrancy and
empty-identity rejection. A write owner increments `writer_depth` on each
reentrant acquisition and releases only when that depth reaches zero. Read-to-
open decisions; neither language may infer them from this candidate. The
additional `tests/fixtures/kernel_sync_vectors.json` freezes reentrant reads,
zero-timeout writer failure, status snapshots, and missing-owner unlock errors;
it does not claim queued-writer fairness or cancellation semantics.

The event bus tracks its own in-flight counter (no CPython
`ThreadPoolExecutor` private access), so a non-CPython worker backend drops in
cleanly. Its dispatch counters are cumulative: `submitted` counts successful
executor submissions, `completed` counts those tasks after callback dispatch
finishes, and `dropped` counts bounded-queue overload or executor submission
failures. `queue_depth` is the current in-flight count and `drop_rate` is
`dropped / (submitted + dropped)`, with zero as the empty denominator case.
The queue benchmark creates a fresh bus for each round, drains it before
sampling these counters, and marks a sample non-clean whenever `dropped > 0`
or the drained `queue_depth` is non-zero; throughput from a lossy or
not-drained round is evidence of overload, not successful delivery.
The standard report carries both the configured overload curve and an
explicit bounded-load curve, so a clean delivery baseline is never inferred
from a saturated sample.

The deterministic EventBus parity fixture
`tests/fixtures/kernel_event_vectors.json` freezes bounded history retention,
type-filtered history, signal serialization, and idle dispatch counters with no
listeners. It does not freeze callback scheduling, overload drops, shutdown
fairness, or runtime SSE/WS fan-out; those remain performance and adapter
evidence.

The deterministic process parity fixture
`tests/fixtures/kernel_process_vectors.json` freezes PID/PCB registration,
READY/RUNNING transitions, identity verification, cancellation terminality,
exit-to-ZOMBIE and reap, resource totals, and timestamp-independent audit
ordering. It does not freeze the Python zombie reaper, interrupt delivery,
allocator/limiter cleanup, long-lived OS handles, or runtime process routing;
those remain adapter-owned effects.

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
