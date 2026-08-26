# Multi-Language Build Boundary

Rust and TypeScript build scaffolding for the language-neutral rewrite
contracts; neither workspace is a Praxis runtime authority. The target Rust
kernel is a clean-break build, not a Python user-data compatibility layer.

## Workspace inventory

| Path | Role | Runtime status |
|---|---|---|
| `crates/` | Cargo workspace for selective L1 mechanism sinks | Build-only; isolated candidates only |
| `crates/l1-kernel-rs/` | Versioned Rust L1 boundary types and isolated mechanism candidates | Candidate-only; no Python bindings, policy, or execution authority |
| `packages/protocol-ts/` | TypeScript mirror of protocol v1 and TS-neutral records | Read-only parity implementation |
| `rust-toolchain.toml` | Rust compiler, formatter, and linter pin | Build input |
| `packages/protocol-ts/package-lock.json` | Reproducible npm dependency graph | Build input |

## Contracts

- Python is the current semantic reference and benchmark baseline. The future
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
  fixtures and do not freeze Python class layout or implementation quirks.
- The Rust `registry_base` candidate mirrors only declarative registry values:
  defaults, duplicate/overwrite semantics, registration order, category filters,
  public views, and counters. `tests/fixtures/kernel_registry_base_vectors.json`
  is the shared source. Python handler closures, domain policy, discovery, and
  runtime registry ownership remain outside the Rust boundary.
- The Rust `registry` candidate mirrors only sorted opaque section snapshots and
  explicit system-summary aggregation. `tests/fixtures/kernel_registry_vectors.json`
  is the shared source; section producers, module/process/device queries,
  syscall discovery, clocks, and runtime registry ownership remain Python-owned.
- The Rust `tool_chain` candidate mirrors only call-field normalization,
  HMAC-SHA256 fingerprint truncation, `GENESIS` fallback, and root-first chain
  verification. `tests/fixtures/kernel_tool_chain_vectors.json` is the shared
  source; key provisioning, call storage, trimming/re-rooting, and execution
  remain Python-owned.
- The Rust `sync` candidate consumes `tests/fixtures/kernel_sync_vectors.json`
  for reentrant reads, zero-timeout writer failure, status snapshots, and
  missing-owner unlock errors. Queue fairness, cancellation, cross-process
  ownership, and runtime lock routing remain outside the candidate.
- The Rust `event` candidate consumes `tests/fixtures/kernel_event_vectors.json`
  for bounded history retention, type-filtered history, signal serialization,
  and idle dispatch counters. Callback scheduling, overload drops, shutdown
  fairness, and SSE/WS fan-out remain outside the deterministic vector.
- Rust test ownership is fully isolated by boundary: mechanism invariants,
  concurrency behavior, public behavior, and cross-language parity tests live
  under `crates/l1-kernel-rs/tests/<domain>/` and consume `tests/fixtures/` when
  vectors are required. `Cargo.toml` explicitly registers each historical
  target name with `autotests = false`; implementation modules contain no
  inline test blocks. `make rust-contract-test` runs the independent domain,
  while `cargo test --test <name>` runs one bounded target.
- The Rust `substrate` module begins the Rust-first R1 base with
  generation-tagged process handles, deterministic shard planning, and
  allocation-free atomic queue metrics. It does not own process storage,
  scheduling, boot, or runtime routing; those require R2/R3 evidence.
- The Rust `benchmark` module defines the fixed-work R2 report schema and
  rejects unknown worker counts, duplicate/out-of-range rounds, incomplete
  work, zero-duration samples, invalid p95/p99 ordering, invalid resource
  availability, and unsupported schema versions. Schema v3 records p95/p99
  tail latency, aggregate queue/lock waits, rejected work, and process CPU/RSS
  deltas. CPU is expressed in nanoseconds and memory in bytes; every value has
  an explicit source or `unavailable` marker. `BenchmarkEvidence` adds a
  validated JSON envelope with platform, architecture, runtime, source
  revision, runner, and resource-unit metadata.
- The Rust `benchmark_runner` module is a measurement-only contention
  candidate: it drains a bounded typed queue after running a fixed total for
  every worker/round pair, samples process resources, and returns a complete v3
  report. It does not own scheduling, boot, or runtime routing. `make
  rust-benchmark` emits Rust evidence; `scripts/py/r2_baseline_bundle.py`
  independently runs the Python reference and validates both reports into one
  comparison artifact.
- The WorkerPool exposes a separate `submit_result_batch` admission boundary.
  `run_worker_pool_batch_submit` and the `rust-worker-batch-submit-bench`
  binary emit the `worker.pool.batch_submit` fixed-work evidence separately
  from the per-task `worker.pool.batch` baseline. Batch admission preserves
  FIFO, oldest-pending eviction, cancellation/result completion, deadline
  propagation for the existing single-task path, and shutdown drain rules;
  admission wakes only the smaller of the submitted batch and resident worker
  count through repeated `notify_one` calls, avoiding an unconditional
  condition-variable broadcast. Evidence must compare throughput, queue wait,
  and tail latency before any runtime policy promotion.
- The Rust `session` candidate provides a sharded `SessionBook` with bounded
  history, authoritative `input_seq` admission, cursor paging, explicit
  created/active/closing/closed/crashed lifecycle, and versioned checkpoint
  values. It is a mechanism-only session truth seam for a future AgentLoop and
  TS bridge; it does not execute prompts/tools, own PTY processes, or replace
  Python session/runtime authority. Its public tests live in
  `crates/l1-kernel-rs/tests/session/session.rs` and `session_vectors.rs`.
- The Rust `session_store` adapter persists the complete `SessionBook` as an
  atomically replaced, versioned document under the fresh Rust state root.
  Clean writes reject active/closing sessions; unclean documents normalize
  non-terminal sessions to explicit `crashed` state and require caller-driven
  recovery. It does not import Python state or execute AgentLoop/provider work.
  Its public behavior is isolated in `crates/l1-kernel-rs/tests/session/session_store.rs`.
  The `rust-session-store-probe` binary is test-only (build with
  `make rust-session-store-probe`): `emit` writes a
  deterministic unclean checkpoint and `validate` reads and validates an
  existing one. The TS `session-store.e2e.test.ts` suite invokes it only when
  the candidate binary is built, so cross-process coverage never becomes a
  hidden in-process substitute or a production entry point.
- The Rust `execution_store` adapter persists SessionBook, TerminalBook, and
  AgentLoopBook metadata as one versioned atomic document. Its TS counterpart
  `execution-checkpoint.ts` is read-only: it validates the same cross-book
  references, lifecycle restrictions, ordering, and JavaScript safe-integer
  boundary, then exposes a defensive snapshot/refresh view. TS cannot recover
  sessions, rebind processes, or write the Rust checkpoint through this seam.
- The session hot path uses hash indexes for duplicate admission while sorting
  only snapshot output for deterministic wire order. `run_session_book` and
  `rust-session-bench` provide a fixed-total `session.book.admission` report
  with throughput, p95/p99, CPU/RSS, and explicit zero rejection/error counts;
  queue wait is zero because no queue boundary is involved, while lock wait
  accumulates only registry-unavailable `try_write` fallbacks. The isolated
  2026-08-23 1/2/4-worker release baseline was about 1.62M/1.46M/1.37M ops/s
  with median blocked-write wait of 0/0.85/3.32 ms, so batch/shard admission
  remains a separate write-scaling candidate.
- `SessionBook::create_batch` groups validated specs by shard and acquires each
  registry lock once while preserving input order and independent failures.
  `session.book.batch_admission` is measured by `rust-session-batch-bench` as a
  separate batch-latency workload; it is not merged into per-session evidence.
- `snapshot::BookSnapshotPage` gives `SessionBook`, `AgentLoopBook`, and
  `TerminalBook` a bounded identity-ordered read page. It retains at most
  `limit + 1` handles in a max-heap while selecting from registry indexes,
  sorts only that retained set, validates limits in `1..=512`, and exposes only
  a live exclusive-identity cursor; durable callers retain complete
  deterministic snapshots. `SessionBook` uses
  shard-local `RwLock` registries so concurrent read pages do not serialize
  behind one mutex. `run_session_book_snapshot_page` and
  `rust-session-snapshot-page-bench` produce independent fixed-work v3
  evidence at 4,096 prebuilt records and 1/2/4 workers. Their lock-wait field
  accumulates only unavailable-lock `try_read` fallbacks, keeping timing out of the
  public API. Two alternating three-round Linux x86_64 release suites pinned
  to CPUs 0-3 recorded former-tree versus max-heap run medians of
  17.8/18.0k versus 20.4/19.5k pages/s at one worker, 31.4/32.4k versus
  35.1/37.1k at two, and 62.4/58.6k versus 63.9/70.1k at four. Every paired
  run had zero rejects, errors, and measured read-lock contention. The
  four-worker p95 varied across suites, so this supports retained-throughput
  improvement rather than a stable tail-latency claim. It is not host-language
  comparison or cutover evidence.
- `run_session_book_snapshot_page_write_contention` is a separate mixed
  workload: each item verifies a 64-item leading page on a single-shard book
  and then admits one unique session. Two alternating release suites pinned
  to CPUs 0-3 completed all 4,096 bundles with zero rejects/errors. Worker
  medians were 12.2/13.1k, 14.1/15.4k, and 13.2/12.8k bundles/s at 1/2/4
  workers; aggregate blocked lock wait was 0 ms, 142-164 ms, and 756-772 ms,
  with p95 bundle latency of 0.10-0.12 ms, 0.28-0.33 ms, and 0.89-0.93 ms.
  The 4-worker plateau and rising wait are explicit evidence that read-page
  throughput cannot be promoted to a write-scaling policy. The runner remains
  measurement-only and has no runtime or cutover authority.
- `SessionBook` shards now keep a private ordered identity index beside the
  hash map. Page reads inspect at most `limit + 1` eligible identities, while
  duplicate checks and direct lookup remain hash-backed; create, batch, restore,
  and closed removal update both indexes under the shard write lock. A pinned
  same-host hash-only reference measured about 1.34/1.33/1.34M
  `session.book.admission` ops/s at 1/2/4 workers versus about 0.87/1.11/1.21M
  for one ordered-index suite. The write-only cost is material, but the mixed
  page/read bundle reached 61.7-66.4k/70.1-82.3k/55.9-57.5k bundles/s and
  reduced aggregate lock wait to 0/14-19/123-127 ms at 1/2/4 workers. These
  fixed-host samples document a read/write tradeoff and do not grant cutover
  authority.
- `AgentLoopBook` and `TerminalBook` keep the same private ordered identity
  index beside their hash maps; registration and checkpoint restore update both
  indexes under one registry write lock, while direct lookup and complete
  snapshots remain unchanged. `run_agent_loop_book_snapshot_page` and
  `run_terminal_book_snapshot_page` emit separate fixed-work v3 reports using
  the standard 4,096-record, 4,096-request, 1/2/4-worker, three-round matrix.
  Their benchmark-only `snapshot_page_with_lock_wait` path clocks only after
  `try_read` reports contention, while the public page API stays uninstrumented.
  One Linux x86_64 release suite pinned to CPUs 0-3 measured median throughput
  of about 54.2k/107.7k/207.3k pages/s for AgentLoopBook and
  114.6k/190.8k/297.9k pages/s for TerminalBook at 1/2/4 workers, with zero
  rejects, errors, and observed read-lock wait. This is a single-host mechanism
  baseline, not an old-code A/B, writer-contention result, or cutover signal.
- The `registry_base` candidate uses a hash index plus an explicit registration
  order vector, so name admission and lookup do not scan all descriptors while
  overwrite and public ordering remain stable. `run_registry_base` and
  `rust-registry-base-bench` emit `registry.base.lookup` under the same v3
  schema. The runner records a candidate baseline only; it does not claim a
  stable speedup until an old-vector reference is measured with the identical
  4096-item, 1/2/4-worker, three-round workload.
- The Rust `agent_loop` candidate owns only logical routing state: it validates
  agent/cell/session/terminal correlation, models loop lifecycle, and admits
  input/events through the Rust `Session` truth root with loop/session admission
  linearized under one loop lock. Provider/model/tool execution, prompt policy,
  PTY/subprocess ownership, terminal mailbox mutation, and runtime scheduling
  remain outside this candidate; its independent tests live in
  `crates/l1-kernel-rs/tests/session/agent_loop.rs`. `run_agent_loop` and the
  `rust-agent-loop-bench` binary emit separate v3 fixed-work evidence with
  loop-mutex wait accounting; the current 4096-item smoke shows decreasing
  throughput and rising wait at 2/4 workers, so no scaling policy is promoted.
  Lock wait is measured only on contended acquisitions; the fast uncontended
  path uses `try_lock` and avoids per-admission clock/atomic instrumentation.
  `AgentLoopHandle::admit_input_batch` is a separate grouped-admission
  candidate: one loop lock covers a caller-sized input group, Session retains
  authoritative sequencing, and per-item failures do not consume command
  sequence numbers. `run_agent_loop_batch` and
  `rust-agent-loop-batch-bench` emit `agent.loop.batch_admission` reports with
  batch-level p95/p99; those samples are not merged with per-input latency.
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
  Rust integration test and the Python adapter test for authorization and
  mutation lifecycle only.
- The Rust `network` module is a clock-injected `PeerBook` candidate for
  endpoint validation, self-ignore, liveness timeout, loss-once, eviction
  grace, and deterministic health/list views. `kernel_peer_vectors.json` is
  consumed by Rust and Python tests; TCP/UDP/TLS, sockets, EventBus, card sync,
  and message envelopes remain adapter-owned.
- The Rust `boot` module is a declarative `BootPlan` candidate for validated
  step metadata, explicit replacement, pre-execution locking, and deterministic
  dependency-first ordering. Missing dependencies, cycles, invalid names, and
  duplicate registrations fail closed. It does not execute callbacks, read
  configuration, start workers, mutate lifecycle state, or wire the Python
  boot registry. `tests/fixtures/kernel_boot_plan_vectors.json` is consumed by
  Rust and Python tests; Python's missing-dependency omission is documented as
  an intentional reference-only difference.
- A locked `BootPlan` also exposes `execute` with an exact caller-supplied
  `BootAction` map. Handler shape is validated before the first callback;
  failures and panics stop the dependency-ordered run with a completed-prefix
  report. This remains a host-owned execution seam and does not grant provider,
  lifecycle, or production boot authority.
- `agent_loop_execution::AgentLoopExecutionBridge` is the bounded execution
  seam above the routing state. It submits a caller-owned `AgentLoopAction` to
  `KernelRuntime`; the worker admits input, invokes the action with its receipt,
  and optionally admits one returned event. Versioned reports retain input/event
  receipts, while structured failures identify admission, action, or
  event-admission stage and any partial input. Pre-execution cancellation cannot
  write session history. The bridge does not discover providers, prompts, tools,
  PTYs, or production policy; `tests/runtime/agent_loop_execution.rs` is its
  independent Rust target.
- The Rust `state_layout` module is the first R4 state-ownership candidate. It
  validates a versioned manifest of canonical relative entries and declared
  parents, then maps explicit host probes to `initialize`, `resume`, `recover`,
  `migrate`, or fail-closed `reject`. It performs no filesystem I/O, directory
  creation, Python-state import, or migration side effect. The shared
  `tests/fixtures/kernel_state_layout_vectors.json` freezes ordering and fresh
  state/recovery decisions; filesystem probes remain a future R4 adapter.
- The Rust `state_store` module is the filesystem-bearing R4 adapter behind
  that manifest. It creates only a fresh Rust root, persists manifest and
  lifecycle/checkpoint records with per-file atomic rename plus `sync_all`,
  and exposes clean resume versus explicit unclean recovery. It rejects
  divergent or migration-required roots and never imports Python state.
- The Rust `ports` module translates the mechanism-port value surface and
  declarative registration metadata: `PortResult`, `Endpoint`, `Message`, and
  privacy-preserving `InputActivitySnapshot`, plus a deterministic
  `PortRegistry` with explicit replacement and lock semantics. It does not
  instantiate or execute process, storage, lock, scheduler, transport, worker,
  or input adapters. `tests/fixtures/kernel_port_vectors.json` is shared with
  the Python reference for value serialization and descriptor order.
- The Rust `assembly` module composes `BootPlan`, `StateLayoutManifest`,
  `ConfigLayoutManifest`, `ProtocolDescriptor`,
  `TerminalContractDescriptor`, `PortRegistry`, and the halted lifecycle into
  a validated `KernelAssembly` snapshot. The standalone `rust-kernel` binary
  requires an explicit state-root argument and emits that complete snapshot
  without importing Python or performing configuration/filesystem/provider
  side effects. Config, protocol, terminal,
  and assembly metadata mismatches fail closed; `state_store` supplies fresh
  state initialization and durable recovery.
- The Rust `preflight` module is a read-only entry preparation seam. Its
  `PreflightRequest` requires explicit assembly metadata and an injected
  `StateProbe`; `inspect` returns the validated snapshot, state action, and
  operator disposition without probing or mutating the host. The standalone
  `rust-kernel-preflight` binary reads one JSON request from stdin and emits
  one JSON report, and `make rust-kernel-preflight` builds it for automation.
  Its tests live in `tests/assembly/preflight.rs`. It does not execute boot,
  create state, rebind processes, or select a Python fallback, so it is
  evidence for R4 assembly rather than an R5 production entrypoint.
- The Rust `entry` module is an explicit one-shot coordinator for a persistent
  Rust runtime. `EntryRequest` carries complete assembly, JSON-safe runtime
  limits, an operation, and an optional exact recovery decision. `inspect`
  reports the root decision without booting; `boot_once` requires a matching
  `RecoverUnclean` acknowledgement, boots, captures the active snapshot, then
  performs bounded clean shutdown. `rust-kernel-entry` and
  `make rust-kernel-entry` provide a bounded JSON stdin/stdout smoke path.
  Invalid limits or stale/missing recovery acknowledgements fail closed. This
  remains an R4 candidate and does not grant production, Python, PTY, provider,
  AgentLoop, or R5 cutover authority.
- The Rust `runtime` candidate composes that locked assembly, lifecycle FSM,
  sharded scheduler state, and bounded WorkerPool into an explicit
  boot/submit/cancel/reap/shutdown host for already-bound Rust closures.
  Submissions take a shared lifecycle barrier while reserving a handle,
  registering it before direct dispatch, and handing it to the WorkerPool;
  boot takes the exclusive side, while shutdown first publishes `Draining` and
  then takes it to drain already-admitted submissions. The task book follows scheduler shard
  selection, so unrelated task records do not share a global mutex.
  `submit_observed` records only contended admission/task-book fallback wait;
  ordinary submissions retain no timing instrumentation. The independent
  `runtime.submit_reap` runner and `rust-runtime-bench` binary report fixed
  work, tail latency, WorkerPool aggregate claim/wake wait, runtime lock wait,
  errors, rejections, and parent-process CPU/RSS deltas. A Linux x86_64
  aligned release sample based on `06e8288c` completed every 4,096-item
  1/2/4-worker, three-round case with zero errors/rejections; median throughput
  was about 18.1k/27.3k/32.1k ops/s, aggregate queue wait was
  155.2/262.8/469.7 ms, and p99 was 140/562/1,342 microseconds. This is a bounded-concurrency
  baseline, not a scaling, L2/TS wire, AgentLoop, provider, or cutover claim.
- `KernelRuntime::submit_batch` reserves and records every handle before one
  grouped WorkerPool handoff, rolling back all prior reservations when one
  cannot be admitted. The separate `runtime.batch_submit_reap` runner and
  `rust-runtime-batch-bench` keep the maximum in-flight batch count inside
  explicit process/queue capacity, return task-count throughput, and report
  p95/p99 per completed group rather than per task. A local unpinned 32-task
  batch sweep completed all 4,096-item 1/2/4-caller, three-round samples with
  zero errors/rejections: median throughput was about 363k/540k/591k tasks/s,
  aggregate queue wait 5.4/8.7/18.7 ms, and observed runtime lock wait
  0/0.086/0.045 ms. Its batch tail distribution is intentionally not compared
  with `runtime.submit_reap` per-task p95/p99; the host-local throughput and
  wait contrast is only evidence to retain the candidate for future review.
- `KernelRuntime::reap_finished(max_tasks)` is a bounded caller-driven
  lifecycle seam. It selects no more than the supplied budget, reaps only
  already-terminal tasks, and reports pending/unavailable/error outcomes;
  zero budgets fail closed. It does not start a background reaper or change
  runtime lifecycle authority.
- The Rust `protocol` module is the retained R4 wire-boundary candidate. It
  validates v1 envelopes and TS-neutral records, canonicalizes JSON with stable
  object ordering, applies the Python/TS optional-field defaults, strips
  unknown record fields, and provides bounded replay/cursor values. Its public
  parity tests live in `crates/l1-kernel-rs/tests/protocol/protocol_vectors.rs` and
  consume `tests/fixtures/protocol_v1_records.json`; HTTP/WS framing, L2
  dispatch, clocks, and runtime session ownership remain adapters.
- The Rust `protocol_host` module is the bounded R4 JSONL adapter seam. It
  rejects oversized frames before protocol decode, exposes a typed `decode_line`
  path for routing without a redundant re-encode, canonicalizes accepted v1
  envelopes, and returns structured failures without dispatching or executing
  them. `rust-protocol-gate` is a no-Python stdin/stdout smoke entrypoint;
  rejected lines are diagnostics only. Its mechanism tests live in the
  independent `crates/l1-kernel-rs/tests/protocol/protocol_host.rs` target, and it does
  not own AgentLoop, provider, session, or runtime authority.
- The TS L2 transport layer now exposes a managed child-process factory for
  the Python reference and Rust `rust-protocol-host`. `PRAXIS_RUST_HOST` is
  opt-in (`1/true/yes/on/rust`); unset or unknown values keep the Python
  rollback path. The factory captures stderr separately, exposes idempotent
  close, and applies the shared 1 MiB UTF-8 frame bound before writing. This
  is a docking/e2e seam only: it does not wire Rust into production boot or
  grant TS ownership of L1 policy.
- The Rust `config_store` module is the clean-break R4 configuration owner. It
  creates a versioned JSON manifest plus separate `config.json` and
  `settings.json` documents, persists revisions through atomic rename and
  `sync_all`, and resumes only a matching Rust root. It never parses Python
  YAML, imports Python settings, executes migrations, or decides engineering
  debug policy; independent tests live in `tests/storage/config_store.rs`.
- The Rust `terminal` module is the lower-layer AgentLoop terminal substrate.
  `TerminalBook` owns unique terminal/session/process bindings, terminal
  lifecycle terminality, and bounded opaque input/output mailboxes with
  sequence and drop accounting. Hash lookup is used internally while snapshots
  are sorted only at the wire boundary. Normal mailbox operations use a
  read-locked registry plus a per-terminal record lock; batch submit/drain
  methods hold that record lock once and preserve per-frame error semantics. The independent
  `terminal.book.mailbox` and `terminal.book.batch_mailbox` fixed-work runners
  report per-frame versus per-batch latency separately through
  `rust-terminal-bench` and `rust-terminal-batch-bench`. It does not create
  PTYs, spawn subprocesses, execute AgentLoops, render output, or own L2/L3
  policy. Its contract tests are `tests/terminal/terminal.rs` and
  `tests/terminal/terminal_vectors.rs`, backed by `tests/fixtures/kernel_terminal_vectors.json`.
- The Rust `state_queue` module is the first Rust-owned state/queue prototype:
  each shard owns its slot map and lifecycle transitions, while
  `BoundedWorkQueue` uses typed work items and fail-fast capacity rejection.
  Queue length and accepted-but-not-completed metric depth are separate; task
  scheduling and boot state remain outside this candidate.
- The Rust `identity_uid` candidate mirrors only prefix/length validation,
  bounded caller-supplied entropy candidates, collision tracking, reset, and
  restore tracking. `tests/fixtures/kernel_identity_uid_vectors.json` is the
  shared source; random entropy, persisted bindings, and identity issuance
  authority remain Python-owned.
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
  remain Python-owned.
- The Rust `health` candidate mirrors explicit subsystem-result aggregation,
  status precedence, counts, retained details, and elapsed-time rounding.
  `tests/fixtures/kernel_health_vectors.json` is shared; module imports,
  clocks, probes, logging, and provider calls remain Python-owned.
- The Rust `swapper` candidate mirrors memory-ring planning from explicit entry
  and pressure snapshots: ring destinations, compaction filters, and action
  flags. `tests/fixtures/kernel_swapper_vectors.json` is shared; MemoryService
  I/O, allocator sampling, clocks, threads, and persistence remain outside.
- `tests/fixtures/kernel_value_vectors.json` is the shared parity source for
  Python and Rust value tests. Serialization must preserve field names,
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
  operations remain Python-owned.
- The Rust `paths` module derives the deployment path set from explicit
  `PathInputs`. `tests/fixtures/kernel_paths_vectors.json` covers CLI project
  and Docker layouts; config/home/environment discovery and directory creation
  remain outside the candidate.
- The Rust `discovery` module mirrors the provider-neutral configuration
  registry: defaults/source snapshots, parsed section overrides, object shallow
  merge, scalar replacement, null-section retention, runtime updates, and
  tool/service fallback queries. `tests/fixtures/kernel_discovery_vectors.json`
  is shared with the Python reference; YAML parsing, directory scanning,
  logging, and boot registration remain Python-owned.
- The Rust `load_adaptive` module mirrors Python's pure worker-sizing control
  law: explicit metrics and timestamp input, EWMA, hysteresis, target-band
  decisions, growth/shrink limits, slow-task fast growth, cooldown, and reset.
  `tests/fixtures/kernel_load_adaptive_vectors.json` is shared by both
  languages; sampling, clock ownership, WorkerPort mutation, and the runtime
  feature flag remain Python-owned.
- The Rust `schema` module mirrors the owner-qualified string-event registry:
  conflict rejection, same-owner updates, sorted snapshots, membership, and
  reset. `tests/fixtures/kernel_schema_vectors.json` is shared with Python;
  L3 catalog contents, boot registration, and event emission remain Python-owned.
- The Rust `rule_descriptor` module mirrors the pure rule value layer:
  severity conversion, PASS/WARN/BLOCK values, descriptor metadata, sorted
  tags, explicit creation time, and an injected checker context. The shared
  `tests/fixtures/kernel_rule_descriptor_vectors.json` freezes serialization;
  rule content and Constitution I/O remain Python-owned.
- The Rust `territory` module provides component-aware lexical subtree checks
  from explicit paths. `tests/fixtures/kernel_territory_vectors.json` covers
  exact, child, root, prefix-collision, dot-dot, empty-base, and explicit
  working-directory cases; filesystem and symlink resolution remain outside.
- The Rust `interrupt` module records the five stable IRQ kinds, per-kind
  sequence counters, normalized JSON payloads, and bounded recent history.
  `tests/fixtures/kernel_interrupt_vectors.json` is the shared value baseline;
  callback dispatch, persistence replay, and process termination remain Python
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
  methods; it does not start a reaper, fire Python interrupts, clean Python
  allocator state, or own long-lived interpreter/OS handles.
- The Rust `process_adapter` module is a bounded one-shot `ProcessPort`
  candidate at the Rust/TS adapter edge. It supports direct argv and a
  terminal-observation execution path; the host probe supplies the executable
  and invocation prefix. Cwd/input/environment options, bounded stdout/stderr
  draining, timeout kill, and structured not-found/execution
  results. Its independent public target is `tests/process/process_adapter.rs`, and
  `run_process_adapter`/`rust-process-adapter-bench` emit a separate
  `process.adapter.oneshot` fixed-work report. The current release smoke is
  about 707/1404/2758 ops/s at 1/2/4 workers with p95 about 1.54/1.56/1.57 ms
  and zero errors/rejections. It does not own PTYs, process groups, reaping,
  ProcessTable registration, capability authorization, AgentLoop execution, or
  runtime authority; long-lived process ownership remains an open adapter
  slice.
- Process benchmark commands are injected as validated direct argv through
  `ProcessBenchmarkCommand`; the runner does not choose a platform shell or
  append shell switches. The benchmark binaries use a direct self-child argv
  with a private marker so the Makefile targets remain runnable without a
  host-specific command fallback. Empty argv and empty arguments are rejected
  before any child can be spawned.
- The Rust `managed_process` module is the bounded lifecycle candidate above
  that value adapter. It owns generation-safe child slots, direct-argv and
  terminal-derived-argv spawn, bounded output drain, caller-controlled stdin, observer `Pending`
  waits, explicit terminate, terminal snapshots, and reap. Its independent
  target is `tests/process/managed_process.rs`; `run_managed_process` and
  `rust-managed-process-bench` emit `process.managed.lifecycle` evidence. A
  current release smoke measured about 707/1391/2761 ops/s at 1/2/4 workers,
  p95 about 1.52/1.55/1.58 ms, and zero errors/rejections. Capacity is
  reserved before spawn. PTY/process-group semantics, capability policy,
  ProcessTable registration, AgentLoop routing, and runtime authority remain
  open adapter/cutover work.
- The Rust `process_group` module adds generation-safe membership and bounded
  caller-driven reaping without owning OS process-group signals or shutdown.
  Its terminal-member counter removes the repeated whole-map terminal scan, and
  `ProcessReaper::sweep` uses a mark-and-reap path that avoids unused snapshots
  and selects only the current member budget instead of cloning unobserved
  handles.
  The independent `process.group.reaper` fixed-work runner and
  `rust-process-group-bench` binary keep this evidence separate from process
  spawn, queue, and session workloads; no runtime authority is promoted.
- `ProcessTableBridge::stop_all_once` provides a one-shot stable-handle stop and
  joint-reap report with explicit timeout and remaining ownership. A zero
  budget fails before child access; the caller still owns repeat policy and
  production shutdown authority.
- `ProcessGroupRuntime::drain_once` adds a one-shot caller-owned stop-all plus
  bounded sweep report, including remaining groups and members; empty groups
  are closed as `Stopped` during the stop request. It does not select a repeat
  policy, spawn a reaper thread, or grant shutdown authority.
- `ProcessGroupSignalPort` is the explicit host adapter seam for actual
  process-group or PTY stop operations. `request_stop_with_signal` supplies a
  generation-tagged termination plan and fail-closes unless the returned
  `ProcessGroupSignalReport` echoes the same group/generation and bounded
  attempted/delivered counts. Signal choice, OS calls, and subsequent reaping
  remain caller-owned.
- The Rust `event` module now contains an isolated EventBus candidate with
  synchronous history, typed/wildcard callbacks, bounded worker delivery,
  explicit overload counters, shutdown draining, and bounded signal-name
  registration. It does not own the Python SSE/WS fan-out or event policy.
- The Rust `channel` module now contains a JSON-only fixed-capacity ring
  candidate with blocking put/get, timeout, overwrite-oldest, peek/drain,
  close wakeups, and utilization reporting. Arbitrary Python objects and
  transport-specific framing remain outside the Port boundary.
- The Rust `allocator` module now contains configuration-injected allocator
  and resource-limiter candidates for allocation/free accounting, expired and
  observe reclamation, bounded OOM victim reclaim, pressure, swap accounting,
  profiles, and cleanup. `tests/fixtures/kernel_resource_vectors.json` freezes
  the ResourceLimiter profile/fallback, signed cost, usage, and cleanup values;
  Interrupt delivery, process termination, and durable swap persistence remain
  Python adapter responsibilities.
- The Rust `worker` module now contains an isolated bounded `WorkerPort`
  candidate with result handles, FIFO pending-task eviction, panic-to-error
  conversion, graceful drain, and idle shrink. It accepts already-bound
  JSON-returning closures only; Python argument binding, adaptive sampling,
  cancellation, and exception mapping remain outside the candidate.
- The Rust `ipc` module now contains isolated `LockMessage`, `LockChannel`,
  and `LockBus` candidates with bounded history, synchronous handler delivery,
  request/response wakeups, timeout cleanup, and reset semantics. It does not
  open sockets or own cross-process lock authority.
- The Rust `persist` module now contains an isolated append-only event journal
  with the Python row shape (`seq`, `event`, `payload`, `ts`), batch append,
  filtering, sequence validation, reopen recovery, and durable flush. JSONL is
  a single-process candidate backend only; Python SQLite, multi-process
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
  mirror Python's registered schema kinds, ordered JSON callbacks (including
  duplicate target registrations), bounded install-time migration runner, and
  structured failure handling. Durable file IO, timestamp policy, settings
  registration, and boot authority remain Python-owned.
- `tests/fixtures/kernel_policy_vectors.json` now provides shared GateChain and
  Constitution decision vectors. Both Python reference tests and Rust
  candidate tests consume the same serialized inputs; provider side effects,
  persistence, and runtime routing are intentionally absent.
- `tests/fixtures/kernel_lifecycle_vectors.json` and
  `tests/fixtures/kernel_versioning_vectors.json` provide shared lifecycle,
  schema-stamping, identity-migration, and fail-closed error vectors. They do
  not authorize Rust runtime routing or replace Python persistence.
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
replace the Python test suite, layer-import gate, parameter checks, or the
fixed-work Amdahl benchmark required before Rust prioritization.

The `terminal_probe` candidate keeps host terminal discovery outside the Rust
kernel. A host adapter injects validated records for CMD, PowerShell 7, Bash,
Git Bash, or any host-defined terminal, including the resolved executable,
invocation prefix, version, encoding, availability, interactive support, PTY
support, and source. `TerminalProbe` filters and orders those records only with
explicit caller policy; it never scans `PATH` or chooses a machine default.
`TerminalObservation::command_argv` is the sole shell argv construction seam
for a future adapter; `PlatformDescriptor` retains metadata but does not build
shell argv or provide a platform fallback.

The T4a `input_activity` candidate freezes the aggregate-only Rust/TypeScript
value contract above the existing `InputActivityPort`. A host adapter supplies
source labels, permission state, keyboard/pointer activity flags, and an
injected observation time. The Rust `InputActivityProbe` and the TypeScript
projection apply the same positive idle window and source-count bound, reject
duplicate or whitespace-bearing labels, future/non-finite timestamps, and
activity asserted without granted permission, and reduce the records to the
existing `InputActivitySnapshot`. Neither side reads device nodes, parses raw
key values or pointer coordinates, or reads a system clock. The shared
`tests/fixtures/kernel_input_activity_vectors.json` fixture is consumed by the
independent Rust `tests/terminal/input_activity.rs` target and the TypeScript
tests. T4b remains open for platform-specific keyboard/pointer adapters and
permission UX; those effects stay outside the kernel value boundary.

The `process_constraints` candidate is the hard Agent-process admission seam.
It evaluates ring, terminal identity/family and invocation, direct/shell mode,
argv/cwd/environment policy, timeout, output/CPU/memory ceilings, and
process-group membership before spawn. It also rejects adapter executable,
cwd, or environment overrides that diverge from the admitted request.
`ProcessGroupRuntime::spawn_constrained` exposes this check-then-spawn path;
`spawn_gated_constrained` requires the explicit `process.spawn` capability,
adds the GateChain-before-constraints boundary, and rejects a gate/process
identity mismatch before the adapter; the low-level `spawn_args` methods remain mechanism helpers, and implicit shell
compatibility entry points have been removed.
The independent Rust test targets are
`tests/terminal/terminal_probe.rs` and `tests/process/process_constraints.rs`; no TS/L2/provider/
runtime authority is added.
