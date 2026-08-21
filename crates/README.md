# Praxis Rust Workspace

This workspace is the staged Rust boundary for the Rust-first L1 kernel
rewrite. The initial `l1-kernel-rs` crate mirrors language-neutral semantic
values and contains isolated mechanism candidates. It has no Python3 bindings,
no runtime authority, and no policy implementation. The final kernel is a
clean-break build with fresh state; these candidates are not a user-data
compatibility layer. A mechanism may enter the independent kernel only after
fixed-work performance evidence, semantic invariant vectors, and a
cutover/recovery decision are complete.

Shared vectors freeze security/control invariants and explicitly retained wire
fields. They do not freeze Python3 class layout, exception text, singleton
ownership, reaper timing, or other implementation quirks.

The new `substrate` module starts the R1 Rust-native base with generation-tagged
process handles, deterministic shard planning, and allocation-free atomic queue
metrics. It does not own process storage, scheduling, boot, or runtime routing;
those remain R2/R3 design work.

The `benchmark` module defines the fixed-work R2 report schema and rejects
unknown worker counts, duplicate/out-of-range rounds, incomplete work,
zero-duration samples, invalid p95/p99 ordering, and unsupported schema
versions. Schema v2 records p95 and p99 tail latency in addition to aggregate
queue/lock waits and rejected work. Consumers derive integer throughput with
`BenchmarkSample::throughput_ops_per_sec`; the runner records evidence only.

The `benchmark_runner` module supplies a measurement-only queue contention
candidate. It runs a fixed total through a bounded typed queue for every
worker/round pair, drains accepted work, and returns a complete v2 report. It
does not choose scheduling policy, own boot state, or grant runtime authority.

`BenchmarkEvidence` wraps a complete report with schema-versioned platform,
architecture, runtime, source-revision, and runner metadata. Its JSON
round-trip validates the metadata and worker/round coverage before export or
ingestion. `make rust-benchmark` runs the release-mode queue smoke and prints
one evidence document; `PRAXIS_RUST_RUNTIME`, `PRAXIS_GIT_REVISION`, and
`PRAXIS_RUST_RUNNER` may override its attribution at runtime. This artifact is
repeatable R1 evidence, not the full R2 baseline: CPU, memory, Python3 reference
measurements, and workload-specific drop analysis remain required before a
performance decision.

The `state_queue` module is the first Rust-owned state/queue prototype: each
shard owns its slot map and lifecycle transitions, while `BoundedWorkQueue`
uses typed work items and fail-fast capacity rejection. Queue length and
accepted-but-not-completed metric depth are intentionally separate; the
prototype does not schedule tasks or own boot state.

The `reputation` module is a Rust-native, policy-injected score ledger for G5
inputs. It clamps finite scores, rejects non-finite values, applies explicit
task/review/dispute deltas, and returns deterministic snapshots. Singleton
ownership, persistence, provider updates, and GateChain routing remain outside
the candidate.

The `notify` module is a side-channel-only bounded buffer with explicit
timestamps, newest-first reads, cumulative drop counts, and reset semantics.
It does not emit EventBus signals or own SSE/WS/webhook delivery.

The `identity_binding` module owns only Rust-native `(cell, role)` metadata:
write authorization, per-Cell capacity, stable identity IDs across rebinds,
bounded domain tags, monotonic revisions, and deterministic snapshots. Prompt
fragments, identity definitions, persistence, event emission, singleton
ownership, and API/L2Shell routing stay outside the kernel candidate. The UID
issuer supplies the first identity ID; the binding registry never accepts a
client replacement on rebind.

`tests/fixtures/kernel_identity_binding_vectors.json` and the matching Rust
integration/Python3 adapter tests freeze only authorization and mutation
lifecycle; prompt text, random UID bodies, and persistence bytes are
intentionally excluded.

The `network` module supplies a clock-injected `PeerBook` for transport-neutral
peer bookkeeping: endpoint validation, self-announce rejection, bounded
timeout/loss/eviction transitions, alive-peer lookup, and deterministic health
and list views. Sockets, UDP/TCP discovery, TLS, EventBus notifications, card
sync, and message envelopes remain adapter-owned. Its shared lifecycle fixture
is `tests/fixtures/kernel_peer_vectors.json`.

The `boot` module is a declarative assembly candidate. `BootPlan` validates step
names, rejects duplicate registrations unless replacement is explicit, supports
a pre-execution lock, and resolves dependency-first order with fail-closed
missing-dependency and cycle errors. It never executes callbacks, reads
configuration, starts workers, mutates lifecycle state, or wires the Python3
boot registry. `tests/fixtures/kernel_boot_plan_vectors.json` is shared with
the Python3 adapter; the fixture records Python3's intentional omission of
missing dependencies so the clean-break Rust boundary does not inherit it.

The `state_layout` module defines the first R4 state-ownership boundary. It
validates a versioned Rust-owned manifest with canonical relative entries and
declared parent directories, then maps host-supplied observations to explicit
`initialize`, `resume`, `recover`, `migrate`, or fail-closed `reject` actions.
It does not create directories, read files, import Python3 state, or run
migrations. `tests/fixtures/kernel_state_layout_vectors.json` is consumed by
the Rust integration test and a Python3 adapter-side reference test; the
future R4 owner will supply filesystem probes and side effects.

The `ports` module now translates the mechanism-port value surface and
declarative registration boundary: `PortResult`, `Endpoint`, `Message`, and
privacy-preserving `InputActivitySnapshot` are validated without side effects,
while `PortRegistry` preserves registration order, rejects invalid/duplicate
names, and supports an explicit pre-wiring lock. It does not instantiate
transport, process, storage, scheduler, or input providers. The shared
`tests/fixtures/kernel_port_vectors.json` fixture covers values and descriptor
ordering for the future Rust adapter layer.

The `assembly` module composes the validated boot plan, state layout, port
registry, and halted lifecycle into a `KernelAssembly` snapshot. The
`rust-kernel` binary is an independent no-Python3 entrypoint that emits this
snapshot as JSON. It is deliberately declarative: it does not read config,
create the state root, execute boot callbacks, or instantiate providers. This
is the R4 assembly seam; filesystem initialization, versioned protocol serving,
and recovery side effects remain subsequent R4 work.

The current contract module mirrors process state/results/options, primitive
JSON values, signal/event records, EventBus counters, and the capability
request/result boundary. `tests/fixtures/kernel_value_vectors.json` is loaded
by both Python3 and Rust tests; JSON numbers retain integer versus fractional
wire shape. The isolated `sync` module contains candidates for Mutex,
Semaphore, Barrier, Condition, and RWLock; RWLock write depth and empty owner
rejection are part of the shared vector contract and are tested independently.
The shared `tests/fixtures/kernel_sync_vectors.json` additionally freezes
reentrant reads, zero-timeout writer failure, status snapshots, and missing-owner
unlock errors. Cross-process IPC, the named registry, deadlock-cycle reporting,
cancellation, and runtime routing remain pending for the sync slice. The isolated `process`
module now mirrors PCB snapshots, lifecycle FSM transitions, cancellation,
resource accounting, and bounded process audit rows. The shared
`tests/fixtures/kernel_process_vectors.json` freezes PID/PCB registration,
READY/RUNNING transitions, cancellation terminality, exit-to-ZOMBIE and reap,
resource totals, identity verification, and timestamp-independent audit order.
Reaper scheduling, Python3 interrupt/allocator cleanup, long-lived OS handles,
and runtime routing remain Python3-owned until a module-specific pilot is approved.

The isolated `event` module mirrors synchronous signal history, typed and
wildcard subscriptions, bounded callback delivery, submitted/completed/dropped
counters, shutdown draining, and bounded dynamic signal registration. It does
not own L3 event policy or SSE/WS fan-out. The shared
`tests/fixtures/kernel_event_vectors.json` freezes bounded history retention,
type filters, signal serialization, and idle dispatch counters; callback
scheduling and overload fairness remain outside the deterministic vector.

The isolated `platform` module mirrors provider-neutral OS values, shell and
grep command descriptions, URL joining, temporary-directory derivation, and
TCP endpoint parsing. It never executes commands, creates directories, or
opens sockets; those remain Python3 adapter responsibilities.

The isolated `paths` module mirrors deployment-mode selection, `PraxisPaths`
child-path derivation, explicit environment/config overrides, and a resettable
in-memory path store. `PathInputs` are injected by the host; environment
discovery, home-directory probing, and layout creation remain outside the
candidate.

The isolated `discovery` module mirrors the three-tier configuration registry:
registered defaults and source snapshots, already parsed section overrides,
object shallow merge, scalar replacement, null-section default retention,
unknown-section ignore behavior, runtime key updates, and tool/service fallback
queries. `tests/fixtures/kernel_discovery_vectors.json` is consumed by both
languages. YAML parsing, discovery-directory scans, logging, boot registration,
and Python3 registry mutation remain adapter-owned.

The isolated `load_adaptive` module mirrors the pure worker-sizing control law:
EWMA smoothing, hysteresis, target-band HOLD, bounded GROW/SHRINK and
GROW_FAST decisions, cooldown, reset, and explicit caller-supplied time.
`tests/fixtures/kernel_load_adaptive_vectors.json` is consumed by both
languages. Sampling, WorkerPort mutation, adaptive enablement, and worker
threads remain Python3-owned.

The isolated `schema` module mirrors the string-event schema registry with
owner conflict checks, same-owner updates, deterministic listing, membership,
and reset. `tests/fixtures/kernel_schema_vectors.json` is consumed by both
languages; the L3 event catalog, boot registration, and event emission remain
adapter-owned.

The isolated `rule_descriptor` module mirrors the pure Constitution descriptor
layer: MUST/SHOULD/MAY severity, PASS/WARN/BLOCK results, metadata and sorted
tags, explicit timestamps, and an injected checker context. The shared
`tests/fixtures/kernel_rule_descriptor_vectors.json` covers value fields;
Markdown, SettingsCenter, rule catalogs, and policy providers remain outside.

The isolated `registry_base` module mirrors the declarative metadata portion of
Python3's `MapRegistry`: descriptor defaults, duplicate rejection or explicit
overwrite, registration order, category filtering, public serialization, and
registration/removal counters. `tests/fixtures/kernel_registry_base_vectors.json`
is consumed by both languages. Handler closures, domain-specific registries,
source discovery, and runtime routing remain adapter-owned.

The isolated `registry` module mirrors only name-sorted opaque JSON section
snapshots and explicit system-summary aggregation. The shared
`tests/fixtures/kernel_registry_vectors.json` covers healthy module counts,
process/device/syscall counts, and caller-supplied time. Section producers,
singleton queries, syscall discovery, clocks, and runtime registry ownership
remain Python3-owned.

The isolated `tool_chain` module mirrors only stable call-field normalization,
HMAC-SHA256 fingerprint truncation, the `GENESIS` fallback, and root-first
chain verification. `tests/fixtures/kernel_tool_chain_vectors.json` is
consumed by both languages. Key provisioning, call storage, trimming,
re-rooting, and execution remain Python3-owned.

Rust test ownership is split by contract boundary: private mechanism and
concurrency invariants remain colocated under `#[cfg(test)]` in `src/`, while
cross-language parity tests consume public APIs from
`crates/l1-kernel-rs/tests/` as integration tests. Shared JSON fixtures stay in
`tests/fixtures/`; run the isolated domain with `make rust-contract-test`.

The isolated `identity_uid` module mirrors the value-only UID issuer boundary:
prefix and body-length validation, bounded entropy candidates, collision
tracking, reset, and existing-UID restoration. The shared
`tests/fixtures/kernel_identity_uid_vectors.json` freezes these values. Random
entropy, persisted bindings, and identity authority remain Python3-owned.

The isolated `device` module mirrors deterministic device bookkeeping:
explicit records, sliding-window rate checks, strict health thresholds, call
counters, summaries, and aggregate type/health stats. The shared
`tests/fixtures/kernel_device_vectors.json` supplies timestamps and policy
thresholds; SettingsCenter, provider connections, health threads, and system
clock access remain Python3-owned.

The isolated `bus` module mirrors SystemBus metadata, registration replacement
in place, parent-available dependency filtering, stable Kahn planning, cycle
errors, and explicit component state labels. The shared
`tests/fixtures/kernel_bus_vectors.json` covers these values. Event handlers,
child-bus routing, health/stats providers, callbacks, and actual component
lifecycle ownership remain Python3-owned.

The isolated `health` module mirrors explicit subsystem-result aggregation:
status precedence, healthy/degraded/failed counts, subsystem retention, and
elapsed-time rounding. The shared
`tests/fixtures/kernel_health_vectors.json` covers these values. Module
imports, clocks, singleton probes, logging, and runtime providers remain
Python3-owned.

The isolated `swapper` module mirrors memory-ring planning only: importance
based ring-2/ring-3 routing, expired short-ring compaction filters, and
pressure action flags. `tests/fixtures/kernel_swapper_vectors.json` is shared;
MemoryService mutation, allocator sampling, clocks, background threads, and
persistence remain Python3-owned.

The isolated `territory` module mirrors boundary-safe lexical subtree checks.
It accepts an explicit working directory for relative inputs, uses component
semantics to reject prefix collisions, and performs no filesystem or symlink
resolution. GateChain and Constitution consume the candidate helper; runtime
policy and adapter-owned path context remain in Python3.

The isolated `interrupt` module mirrors the five Python3 IRQ kinds, per-kind
sequence counters, empty-payload normalization, and bounded recent history.
It records values behind a mutex but does not execute callbacks, emit signals,
replay persistence, or terminate processes; those effects stay with Python3
adapters.

The isolated `errors` module mirrors the built-in error-code catalog, fallback
messages, Python3-compatible failure responses, cause truncation, and explicit
trace propagation values. It does not resolve locales, inspect stacks, capture
to ErrorBus, or persist logs; those remain adapter responsibilities.

The isolated `channel` module mirrors the fixed-capacity `ChannelPort` ring for
JSON values: blocking put/get with deadlines, overwrite-oldest mode,
peek/drain, close wakeups, and utilization. Arbitrary Python3 objects and
transport framing remain outside the boundary.

The isolated `allocator` module contains configuration-injected allocator and
resource-limiter candidates for allocation/free accounting, expired/observe
reclamation, bounded OOM victim reclaim, pressure, swap accounting, profiles,
and cleanup. Interrupt delivery, process termination, and durable persistence
remain Python3 adapter responsibilities.

The `ResourceLimiter` portion additionally consumes
`tests/fixtures/kernel_resource_vectors.json`, freezing injected profiles,
fallback lookup, signed check/release costs, usage snapshots, profile cleanup,
and arbitrary-resource release behavior. Python3 role configuration remains the
source of profile data; the Rust candidate does not own policy discovery.

The isolated `worker` module mirrors the bounded `WorkerPort` shape: minimum
and maximum resident workers, FIFO eviction of pending work under backpressure,
result handles, panic-to-error conversion, graceful draining, and idle shrink
to the configured floor. Tasks are already-bound Rust closures returning JSON
values; argument binding, adaptive sampling, task cancellation, and Python3
exception mapping remain adapter responsibilities.

The isolated `ipc` module mirrors the lock IPC value and registry shape:
`LockMessage`, bounded `LockChannel` history, synchronous handlers,
request/response wakeups with timeout cleanup, and resettable `LockBus`
registration. It is an in-process candidate; socket transport and cross-process
ownership remain outside the boundary.

The isolated `persist` module mirrors the append-only event-journal record and
query shape (`seq`, `event`, `payload`, `ts`), batch append, type filtering,
sequence checks, reopen recovery, and durable flush. It uses JSONL for the
candidate backend within one process; Python3 SQLite storage, multi-process
coordination, and replay policy remain adapter-owned.

The isolated `audit` module provides a bounded chronological `AuditLog` with
identity filtering, bounded detail fields, and optional `EventStore` journal
wiring. Journal failures are counted without changing the in-memory result.
The isolated `capability` module provides one fail-closed execution authority:
an unwired call is denied and audited, wired executor panics become structured
failures, and every invocation is recorded. Executor wiring remains an
adapter/boot responsibility; the candidate does not implement G1-G5 policy or
route production calls.

The isolated `gatechain` module mirrors the pure G1-G5 decision shape. It has
data-only policy thresholds, a fail-closed whitelist, injected process or
interactive identity snapshots, boundary-safe territory checks, danger and
frequency scoring, explicit G4 authorization inputs, reputation/history G5
decisions, structured steps, and a bounded history ledger. Posture, reputation,
approval, event, and boot providers remain adapter-owned; no Rust gate result
authorizes a production call.

The isolated `constitution` module mirrors the pure rule layer: serialized
MUST/SHOULD/MAY descriptors, PASS/WARN/BLOCK results, action-category
prefiltering, territory/sandbox/constitution/scout/cross-territory checks,
GateChain markers, and explicit offensive-skill posture inputs. Markdown
parsing/rendering, custom-rule persistence, NMI/EventBus emission, and skill or
posture provider lookup remain Python3/adapter responsibilities.

The isolated `vfs` module mirrors the provider-neutral L1 filesystem boundary:
bounded mount registration, longest-prefix resolution, ring/read-only checks,
virtual-file storage, provider-read caching with TTL and invalidation, and
structured `resolve_mount` metadata. Real files, `/proc`, `/sys`, `/skills`,
`/dev`, symlink policy, and provider writes remain outside Rust; non-virtual
operations return `EADAPTER` until a versioned adapter contract and rollback
pilot exist.

The isolated `lifecycle` module mirrors the provider-neutral lifecycle FSM and
checkpoint record: halted/installing/booting/active/draining/crashed states,
validated transitions, boot/shutdown bookkeeping, install/recovery decisions,
and JSON encode/decode. It does not inspect the filesystem or persist a
checkpoint by itself; a Python3-owned adapter remains responsible for durable
storage and boot wiring.

The isolated `versioning` module mirrors the six kinds currently registered by
Python3 (`snapshot`, `checkpoint`, `card_registry`, `todo_table`,
`transaction_area`, and `capability_gate`). It stamps primitive JSON objects,
applies ordered callbacks, and returns structured future/missing/failure
errors. The `migration` module mirrors the ordered install-time runner,
including duplicate target registrations in registration order, bounded target
selection, first-error stop, and panic-to-error conversion. Settings, provider
migrations, and runtime install authority stay Python3-owned.

`tests/fixtures/kernel_policy_vectors.json` is the shared parity source for
the GateChain and Constitution candidates. Rust and Python3 tests consume the
same block/pass cases; provider side effects and runtime routing are excluded
from the fixture by design.

`tests/fixtures/kernel_vfs_vectors.json` is the shared mount-resolution source
for the VFS candidate and Python3 reference. It freezes only stable prefix,
relative-path, root, ring, and read-only fields; provider I/O remains excluded.

`tests/fixtures/kernel_lifecycle_vectors.json` and
`tests/fixtures/kernel_versioning_vectors.json` are shared parity sources for
the lifecycle and schema candidates. They freeze only deterministic state,
JSON, and error fields; timestamp generation, filesystem persistence, and
migration side effects remain adapter-owned.

```bash
cargo test --workspace --manifest-path crates/Cargo.toml
cargo fmt --manifest-path crates/Cargo.toml --all -- --check
cargo clippy --manifest-path crates/Cargo.toml --workspace --all-targets --all-features -- -D warnings
```
