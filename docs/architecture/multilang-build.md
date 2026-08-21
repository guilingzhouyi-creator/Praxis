# Multi-Language Build Boundary

Rust and TypeScript build scaffolding for the language-neutral rewrite
contracts; neither workspace is a Praxis runtime authority. The target Rust
kernel is a clean-break build, not a Python3 user-data compatibility layer.

## Workspace inventory

| Path | Role | Runtime status |
|---|---|---|
| `crates/` | Cargo workspace for selective L1 mechanism sinks | Build-only; isolated candidates only |
| `crates/l1-kernel-rs/` | Versioned Rust L1 boundary types and isolated mechanism candidates | Candidate-only; no Python3 bindings, policy, or execution authority |
| `packages/protocol-ts/` | TypeScript mirror of protocol v1 and TS-neutral records | Read-only parity implementation |
| `rust-toolchain.toml` | Rust compiler, formatter, and linter pin | Build input |
| `packages/protocol-ts/package-lock.json` | Reproducible npm dependency graph | Build input |

## Contracts

- Python3 is the current semantic reference and benchmark baseline. The future
  Rust kernel is an independent build with fresh state and may redesign
  internals, schemas, and scheduling once the retained wire boundaries are
  explicitly classified.
- TypeScript consumes the shared protocol fixture and never owns L2, L3A,
  AgentLoop, tool, memory, or workflow state.
- Rust currently exposes the contract descriptor plus primitive value types
  for process, event, EventBus, and capability boundaries. Isolated candidates
  cover synchronization, process lifecycle, event delivery, JSON channels,
  allocator/resource accounting, bounded WorkerPort execution, lock IPC, and
  append-only event journaling. It still
  has no execution authority. A candidate can move behind a port only after a
  fixed-work performance result, semantic invariant vectors, and a clean
  cutover/recovery decision exist. Shared vectors are not user-data migration
  fixtures and do not freeze Python3 class layout or implementation quirks.
- The Rust `registry_base` candidate mirrors only declarative registry values:
  defaults, duplicate/overwrite semantics, registration order, category filters,
  public views, and counters. `tests/fixtures/kernel_registry_base_vectors.json`
  is the shared source. Python3 handler closures, domain policy, discovery, and
  runtime registry ownership remain outside the Rust boundary.
- The Rust `registry` candidate mirrors only sorted opaque section snapshots and
  explicit system-summary aggregation. `tests/fixtures/kernel_registry_vectors.json`
  is the shared source; section producers, module/process/device queries,
  syscall discovery, clocks, and runtime registry ownership remain Python3-owned.
- The Rust `tool_chain` candidate mirrors only call-field normalization,
  HMAC-SHA256 fingerprint truncation, `GENESIS` fallback, and root-first chain
  verification. `tests/fixtures/kernel_tool_chain_vectors.json` is the shared
  source; key provisioning, call storage, trimming/re-rooting, and execution
  remain Python3-owned.
- The Rust `sync` candidate consumes `tests/fixtures/kernel_sync_vectors.json`
  for reentrant reads, zero-timeout writer failure, status snapshots, and
  missing-owner unlock errors. Queue fairness, cancellation, cross-process
  ownership, and runtime lock routing remain outside the candidate.
- The Rust `event` candidate consumes `tests/fixtures/kernel_event_vectors.json`
  for bounded history retention, type-filtered history, signal serialization,
  and idle dispatch counters. Callback scheduling, overload drops, shutdown
  fairness, and SSE/WS fan-out remain outside the deterministic vector.
- Rust test ownership is split by boundary: private mechanism invariants remain
  inline in `src/`, while public cross-language parity tests live under
  `crates/l1-kernel-rs/tests/` and consume `tests/fixtures/`; `make
  rust-contract-test` runs the independent contract-test domain.
- The Rust `substrate` module begins the Rust-first R1 base with
  generation-tagged process handles, deterministic shard planning, and
  allocation-free atomic queue metrics. It does not own process storage,
  scheduling, boot, or runtime routing; those require R2/R3 evidence.
- The Rust `benchmark` module defines the fixed-work R2 report schema and
  rejects unknown worker counts, duplicate/out-of-range rounds, incomplete
  work, zero-duration samples, invalid p95/p99 ordering, and unsupported schema
  versions. Schema v2 records p95/p99 tail latency, aggregate queue/lock waits,
  and rejected work; consumers derive integer throughput from completed work
  and elapsed time. `BenchmarkEvidence` adds a validated JSON envelope with
  platform, architecture, runtime, source revision, and runner metadata.
- The Rust `benchmark_runner` module is a measurement-only contention
  candidate: it drains a bounded typed queue after running a fixed total for
  every worker/round pair and returns a complete v2 report. It does not own
  scheduling, boot, or runtime routing. `make rust-benchmark` emits this
  release-mode evidence; CPU, memory, and Python3-reference measurements remain
  separate R2 work.
- The Rust `reputation` module is a policy-injected score ledger candidate for
  G5 inputs. It clamps finite scores, applies explicit outcome deltas, and
  returns deterministic snapshots; singleton, persistence, provider, and
  GateChain routing remain outside the Rust boundary.
- The Rust `notify` module is a side-channel-only bounded buffer candidate with
  explicit timestamps, newest-first reads, drop counters, and reset semantics;
  EventBus/SSE/WS/webhook delivery remains adapter-owned.
- The Rust `identity_binding` module is a mechanism-only metadata candidate:
  fail-closed write authorization, bounded per-Cell role cardinality, stable
  identity IDs across rebinds, bounded domain tags, monotonic revisions, and
  deterministic snapshots. Prompt text/definitions, persistence, singleton
  state, event emission, and API/L2Shell routing stay outside the Rust build.
  `tests/fixtures/kernel_identity_binding_vectors.json` is consumed by the
  Rust integration test and the Python3 adapter test for authorization and
  mutation lifecycle only.
- The Rust `network` module is a clock-injected `PeerBook` candidate for
  endpoint validation, self-ignore, liveness timeout, loss-once, eviction
  grace, and deterministic health/list views. `kernel_peer_vectors.json` is
  consumed by Rust and Python3 tests; TCP/UDP/TLS, sockets, EventBus, card sync,
  and message envelopes remain adapter-owned.
- The Rust `boot` module is a declarative `BootPlan` candidate for validated
  step metadata, explicit replacement, pre-execution locking, and deterministic
  dependency-first ordering. Missing dependencies, cycles, invalid names, and
  duplicate registrations fail closed. It does not execute callbacks, read
  configuration, start workers, mutate lifecycle state, or wire the Python3
  boot registry. `tests/fixtures/kernel_boot_plan_vectors.json` is consumed by
  Rust and Python3 tests; Python3's missing-dependency omission is documented as
  an intentional reference-only difference.
- The Rust `state_layout` module is the first R4 state-ownership candidate. It
  validates a versioned manifest of canonical relative entries and declared
  parents, then maps explicit host probes to `initialize`, `resume`, `recover`,
  `migrate`, or fail-closed `reject`. It performs no filesystem I/O, directory
  creation, Python3-state import, or migration side effect. The shared
  `tests/fixtures/kernel_state_layout_vectors.json` freezes ordering and fresh
  state/recovery decisions; filesystem probes remain a future R4 adapter.
- The Rust `ports` module translates the mechanism-port value surface and
  declarative registration metadata: `PortResult`, `Endpoint`, `Message`, and
  privacy-preserving `InputActivitySnapshot`, plus a deterministic
  `PortRegistry` with explicit replacement and lock semantics. It does not
  instantiate or execute process, storage, lock, scheduler, transport, worker,
  or input adapters. `tests/fixtures/kernel_port_vectors.json` is shared with
  the Python3 reference for value serialization and descriptor order.
- The Rust `assembly` module composes `BootPlan`, `StateLayoutManifest`,
  `PortRegistry`, and the halted lifecycle into a validated `KernelAssembly`
  snapshot. The standalone `rust-kernel` binary emits that snapshot without
  importing Python3 or performing configuration/filesystem/provider side
  effects. It establishes the R4 assembly seam; state initialization,
  versioned protocol serving, and recovery effects remain subsequent work.
- The Rust `state_queue` module is the first Rust-owned state/queue prototype:
  each shard owns its slot map and lifecycle transitions, while
  `BoundedWorkQueue` uses typed work items and fail-fast capacity rejection.
  Queue length and accepted-but-not-completed metric depth are separate; task
  scheduling and boot state remain outside this candidate.
- The Rust `identity_uid` candidate mirrors only prefix/length validation,
  bounded caller-supplied entropy candidates, collision tracking, reset, and
  restore tracking. `tests/fixtures/kernel_identity_uid_vectors.json` is the
  shared source; random entropy, persisted bindings, and identity issuance
  authority remain Python3-owned.
- The Rust `device` candidate mirrors explicit device records, rate-window
  pruning, strict health thresholds, call counters, summaries, and aggregate
  stats with caller-supplied timestamps. `tests/fixtures/kernel_device_vectors.json`
  is shared; provider connections, SettingsCenter defaults, health threads, and
  system-clock access remain outside the candidate.
- The Rust `bus` candidate mirrors SystemBus metadata, in-place replacement
  while preserving registration order, parent-available dependency filtering,
  stable topological planning, cycle errors, and explicit state labels.
  `tests/fixtures/kernel_bus_vectors.json` is shared; event callbacks,
  child-bus routing, health/stats providers, and runtime lifecycle ownership
  remain Python3-owned.
- The Rust `health` candidate mirrors explicit subsystem-result aggregation,
  status precedence, counts, retained details, and elapsed-time rounding.
  `tests/fixtures/kernel_health_vectors.json` is shared; module imports,
  clocks, probes, logging, and provider calls remain Python3-owned.
- The Rust `swapper` candidate mirrors memory-ring planning from explicit entry
  and pressure snapshots: ring destinations, compaction filters, and action
  flags. `tests/fixtures/kernel_swapper_vectors.json` is shared; MemoryService
  I/O, allocator sampling, clocks, threads, and persistence remain outside.
- `tests/fixtures/kernel_value_vectors.json` is the shared parity source for
  Python3 and Rust value tests. Serialization must preserve field names,
  defaults, error strings, and JSON number shape.
- The Rust `sync` module now contains isolated candidates for `Mutex`,
  `Semaphore`, `Barrier`, `Condition`, and `RWLock`. RWLock write depth and
  empty identity behavior are covered by the shared value fixture. They are not
  wired into `ProcessPort`, `LockPort`, boot, or capability execution. Cross-process IPC,
  the named registry, deadlock-cycle reporting, and cancellation tokens remain
  outside this candidate until their contracts are frozen and tested.
- The Rust `platform` module is a side-effect-free mirror of platform values
  and command descriptions. `tests/fixtures/kernel_platform_vectors.json`
  covers POSIX/Windows shell and grep construction, URL joining, temporary
  path derivation, and TCP endpoint parsing. Subprocess, filesystem, and socket
  operations remain Python3-owned.
- The Rust `paths` module derives the deployment path set from explicit
  `PathInputs`. `tests/fixtures/kernel_paths_vectors.json` covers CLI project
  and Docker layouts; config/home/environment discovery and directory creation
  remain outside the candidate.
- The Rust `discovery` module mirrors the provider-neutral configuration
  registry: defaults/source snapshots, parsed section overrides, object shallow
  merge, scalar replacement, null-section retention, runtime updates, and
  tool/service fallback queries. `tests/fixtures/kernel_discovery_vectors.json`
  is shared with the Python3 reference; YAML parsing, directory scanning,
  logging, and boot registration remain Python3-owned.
- The Rust `load_adaptive` module mirrors Python3's pure worker-sizing control
  law: explicit metrics and timestamp input, EWMA, hysteresis, target-band
  decisions, growth/shrink limits, slow-task fast growth, cooldown, and reset.
  `tests/fixtures/kernel_load_adaptive_vectors.json` is shared by both
  languages; sampling, clock ownership, WorkerPort mutation, and the runtime
  feature flag remain Python3-owned.
- The Rust `schema` module mirrors the owner-qualified string-event registry:
  conflict rejection, same-owner updates, sorted snapshots, membership, and
  reset. `tests/fixtures/kernel_schema_vectors.json` is shared with Python3;
  L3 catalog contents, boot registration, and event emission remain Python3-owned.
- The Rust `rule_descriptor` module mirrors the pure rule value layer:
  severity conversion, PASS/WARN/BLOCK values, descriptor metadata, sorted
  tags, explicit creation time, and an injected checker context. The shared
  `tests/fixtures/kernel_rule_descriptor_vectors.json` freezes serialization;
  rule content and Constitution I/O remain Python3-owned.
- The Rust `territory` module provides component-aware lexical subtree checks
  from explicit paths. `tests/fixtures/kernel_territory_vectors.json` covers
  exact, child, root, prefix-collision, dot-dot, empty-base, and explicit
  working-directory cases; filesystem and symlink resolution remain outside.
- The Rust `interrupt` module records the five stable IRQ kinds, per-kind
  sequence counters, normalized JSON payloads, and bounded recent history.
  `tests/fixtures/kernel_interrupt_vectors.json` is the shared value baseline;
  callback dispatch, persistence replay, and process termination remain Python3
  adapter responsibilities.
- The Rust `errors` module mirrors the built-in error catalog, unknown-code
  fallback, `success=false` response shape, bounded causes, and explicit trace
  values. `tests/fixtures/kernel_error_vectors.json` covers these pure values;
  i18n, ErrorBus capture, stack inspection, and log persistence remain outside.
- The Rust `process` module now contains an isolated PCB/process-table
  candidate for lifecycle FSM transitions, cancellation, resource accounting,
  and bounded audit snapshots. The shared
  `tests/fixtures/kernel_process_vectors.json` freezes PID/PCB registration,
  READY/RUNNING transitions, cancellation terminality, exit-to-ZOMBIE and
  reap, resource totals, identity verification, and timestamp-independent
  audit order. It returns cloned value records and explicit table update
  methods; it does not start a reaper, fire Python3 interrupts, clean Python3
  allocator state, or own long-lived interpreter/OS handles.
- The Rust `event` module now contains an isolated EventBus candidate with
  synchronous history, typed/wildcard callbacks, bounded worker delivery,
  explicit overload counters, shutdown draining, and bounded signal-name
  registration. It does not own the Python3 SSE/WS fan-out or event policy.
- The Rust `channel` module now contains a JSON-only fixed-capacity ring
  candidate with blocking put/get, timeout, overwrite-oldest, peek/drain,
  close wakeups, and utilization reporting. Arbitrary Python3 objects and
  transport-specific framing remain outside the Port boundary.
- The Rust `allocator` module now contains configuration-injected allocator
  and resource-limiter candidates for allocation/free accounting, expired and
  observe reclamation, bounded OOM victim reclaim, pressure, swap accounting,
  profiles, and cleanup. `tests/fixtures/kernel_resource_vectors.json` freezes
  the ResourceLimiter profile/fallback, signed cost, usage, and cleanup values;
  Interrupt delivery, process termination, and durable swap persistence remain
  Python3 adapter responsibilities.
- The Rust `worker` module now contains an isolated bounded `WorkerPort`
  candidate with result handles, FIFO pending-task eviction, panic-to-error
  conversion, graceful drain, and idle shrink. It accepts already-bound
  JSON-returning closures only; Python3 argument binding, adaptive sampling,
  cancellation, and exception mapping remain outside the candidate.
- The Rust `ipc` module now contains isolated `LockMessage`, `LockChannel`,
  and `LockBus` candidates with bounded history, synchronous handler delivery,
  request/response wakeups, timeout cleanup, and reset semantics. It does not
  open sockets or own cross-process lock authority.
- The Rust `persist` module now contains an isolated append-only event journal
  with the Python3 row shape (`seq`, `event`, `payload`, `ts`), batch append,
  filtering, sequence validation, reopen recovery, and durable flush. JSONL is
  a single-process candidate backend only; Python3 SQLite, multi-process
  coordination, and replay handlers remain outside the Rust boundary.
- The Rust `audit` module now contains a bounded chronological audit ring with
  identity filtering, bounded detail fields, and optional `EventStore` journal
  wiring. Journal errors are counted and do not mutate the in-memory result.
- The Rust `capability` module now contains an isolated single execution
  authority with fail-closed unwired behavior, panic-to-structured-error
  conversion, and per-invocation audit. Boot/executor wiring, G1-G5 policy,
  and production routing remain outside the candidate.
- The Rust `gatechain` module now contains a pure G1-G5 candidate with
  data-only thresholds, fail-closed whitelist, injected process/interactive
  identity, boundary-safe territory checks, danger/frequency scoring, explicit
  G4 authorization inputs, G5 reputation/history decisions, structured steps,
  and a bounded ledger. Posture, approval, reputation providers, event side
  effects, boot wiring, and production authority remain outside it.
- The Rust `constitution` module now contains a pure rule/value evaluator with
  serialized MUST/SHOULD/MAY descriptors, PASS/WARN/BLOCK reports,
  action-category filtering, territory/sandbox/constitution/scout/cross-
  territory checks, GateChain markers, and explicit offensive-skill posture
  inputs. Markdown/SettingsCenter IO, NMI/EventBus effects, and provider
  lookups remain outside the candidate.
- The Rust `lifecycle` module now contains the provider-neutral lifecycle FSM,
  checkpoint record, boot/shutdown bookkeeping, install/recovery decision, and
  JSON restore validation. The Rust `versioning` and `migration` modules now
  mirror Python3's registered schema kinds, ordered JSON callbacks (including
  duplicate target registrations), bounded install-time migration runner, and
  structured failure handling. Durable file IO, timestamp policy, settings
  registration, and boot authority remain Python3-owned.
- `tests/fixtures/kernel_policy_vectors.json` now provides shared GateChain and
  Constitution decision vectors. Both Python3 reference tests and Rust
  candidate tests consume the same serialized inputs; provider side effects,
  persistence, and runtime routing are intentionally absent.
- `tests/fixtures/kernel_lifecycle_vectors.json` and
  `tests/fixtures/kernel_versioning_vectors.json` provide shared lifecycle,
  schema-stamping, identity-migration, and fail-closed error vectors. They do
  not authorize Rust runtime routing or replace Python3 persistence.
- Build checks are explicit and reproducible: `npm ci`, TypeScript tests and
  typecheck, Cargo tests, rustfmt check, and clippy with warnings denied.

## Local gates

```bash
make ts-test
make ts-typecheck
make rust-test
make rust-fmt-check
make rust-clippy
make rust-benchmark
make language-check
```

The `language-check` target is a build-environment gate only. It does not
replace the Python3 test suite, layer-import gate, parameter checks, or the
fixed-work Amdahl benchmark required before Rust prioritization.
