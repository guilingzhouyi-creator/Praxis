# Praxis Rust Workspace

This workspace is the staged Rust boundary for the Rust-first L1 kernel
rewrite. The initial `l1-kernel-rs` crate mirrors language-neutral semantic
values and contains isolated mechanism candidates. It has no Python bindings,
no runtime authority, and no policy implementation. The final kernel is a
clean-break build with fresh state; these candidates are not a user-data
compatibility layer. A mechanism may enter the independent kernel only after
fixed-work performance evidence, semantic invariant vectors, and a
cutover/recovery decision are complete.

Shared vectors freeze security/control invariants and explicitly retained wire
fields. They do not freeze Python class layout, exception text, singleton
ownership, reaper timing, or other implementation quirks.

The new `substrate` module starts the R1 Rust-native base with generation-tagged
process handles, deterministic shard planning, and allocation-free atomic queue
metrics. It does not own process storage, scheduling, boot, or runtime routing;
those remain R2/R3 design work.

The `benchmark` module defines the fixed-work R2 report schema and rejects
unknown worker counts, duplicate/out-of-range rounds, incomplete work,
zero-duration samples, invalid p95/p99 ordering, and unsupported schema
versions. Schema v3 records p95 and p99 tail latency, aggregate queue/lock
waits, rejected work, and explicit CPU/memory resource samples. Resource values
use nanoseconds and bytes; unavailable platform samplers are represented by
`null` plus an `unavailable` source. Consumers derive integer throughput with
`BenchmarkSample::throughput_ops_per_sec`; the runner records evidence only.

The `benchmark_runner` module supplies a measurement-only queue contention
candidate. It runs a fixed total through a bounded typed queue for every
worker/round pair, drains accepted work, samples process resources, and returns
a complete v3 report. It does not choose scheduling policy, own boot state, or
grant runtime authority. Batch consumers use one completion counter update for
each bounded drain, preserving queue-depth saturation while reducing atomic
hot-path churn. It also exposes `run_worker_pool_batch` and the independent
`rust-worker-bench` binary for the public WorkerPool boundary; this workload is
kept separate from the lower-level queue contention report so task handoff and
metrics costs are not conflated.

`WorkerPool::submit_result_batch` and the independent
`rust-worker-batch-submit-bench` binary provide a grouped-admission candidate.
The `worker.pool.batch_submit` report uses the same fixed-work schema and
queue-capacity rule as the per-task baseline, but measures batch admission as
its own latency distribution. It preserves FIFO, oldest-pending eviction,
closed-pool completion, and public task-handle semantics; the release evidence
must be compared on throughput, queue wait, p95, and p99 before a runtime
policy can adopt it.

The `session` module adds the P0 session-truth mechanism needed before a clean
AgentLoop bridge: a sharded `SessionBook`, bounded per-session history,
authoritative `input_seq`, cursor pages, explicit crash recovery, and a
versioned checkpoint envelope. Admission uses per-shard locks and a per-session
message-id index; no prompt, tool, PTY, provider, or runtime authority crosses
this boundary. Its public behavior is tested only through the independent
`tests/session/session.rs` and `tests/session/session_vectors.rs` targets.

The `session_store` adapter persists the complete session book under the fresh
Rust state root with a versioned JSON checkpoint and atomic rename. It rejects
clean writes while sessions are active/closing, and loads unclean documents as
explicitly crashed sessions that require caller-driven recovery. It never
imports Python state or executes AgentLoop/provider work; its behavior is
covered by the independent `tests/session/session_store.rs` target.

The `execution_store` adapter adds the combined R4/R5 checkpoint for session,
terminal, and AgentLoop metadata at
`snapshots/execution/checkpoint.json`. It uses atomic replacement and sorted,
cross-referenced records, rejects clean snapshots containing writable state,
live process bindings, or queued terminal frames, and normalizes unclean
sessions/loops/terminals to explicit recovery states. Process ownership,
PTY/mailbox bytes, providers, and runtime authority are deliberately absent;
`tests/session/execution_store.rs` is the independent integration target.

The session hot path uses hash indexes for per-session message IDs and sharded
session admission; deterministic snapshots still sort by session identity.
`run_session_book` and `rust-session-bench` measure fixed-total create/activate/
input work under the standard schema. The runner records throughput, p95/p99,
CPU/RSS, and zero rejection/error counts; queue and lock waits remain zero
because this workload has no separate queue boundary.

`SessionBook::create_batch` is a separate grouped-admission candidate. It
validates inputs first, acquires each shard lock once, preserves input order,
and returns per-item failures without rolling back successful peers. The
`session.book.batch_admission` runner and `rust-session-batch-bench` report
batch-level p95/p99 separately from per-session admission evidence.

The `agent_loop` module is a logical routing candidate above the session and
terminal substrates. `AgentLoopBook` validates agent/cell/session/terminal
correlation, owns loop lifecycle, and admits input/events while serializing loop
state with the SessionBook write. It does not execute providers, prompts, tools,
PTYs, subprocesses, terminal mailbox I/O, or WorkerPool tasks; those remain
adapter-owned. Its public behavior lives in the independent
`crates/l1-kernel-rs/tests/session/agent_loop.rs` target. `run_agent_loop` and the
`rust-agent-loop-bench` binary measure fixed-total input admission with the
same v3 schema and loop-mutex wait field; current release evidence shows the
shared routing lock is a scaling bottleneck, so this remains candidate-only.
The `lock_wait_ns` field records only time spent after a contended `try_lock`
fallback; uncontended admissions avoid clock reads and atomic metric updates.
`AgentLoopHandle::admit_input_batch` and `AgentLoopBook::admit_input_batch` add
the grouped admission candidate: one loop-state lock and one Session history
lock cover a caller-sized input group, while results retain input order and
failed items do not consume command sequence numbers. `run_agent_loop_batch`
and `rust-agent-loop-batch-bench` emit `agent.loop.batch_admission` evidence
with batch-level p95/p99, kept separate from the per-input workload. A batch
report is not a direct replacement for the per-input tail distribution and
does not authorize runtime cutover.

The `process_adapter` module is a bounded one-shot `ProcessPort` candidate for
the future Rust/TS adapter edge. It supports direct argument execution and an
explicit shell path, optional cwd/input/environment/executable values, separate
stdout/stderr drain threads with per-stream retention limits, timeout kill, and
structured not-found/execution/timeout results. `tests/process/process_adapter.rs` is
the independent public test target; `run_process_adapter` and
`rust-process-adapter-bench` measure `process.adapter.oneshot` separately from
ProcessTable and WorkerPool workloads. A current release smoke measured roughly
707/1404/2758 ops/s at 1/2/4 workers with p95 about 1.54/1.56/1.57 ms and zero
errors/rejections. This adapter deliberately owns no long-lived child handles,
PTY/process groups, reaper, ProcessTable registration, capability gate,
AgentLoop execution, or production runtime authority; those are separate
mechanism and cutover work.

The `managed_process` module is the next bounded lifecycle candidate. It owns
generation-safe child slots, direct-args/shell spawn, bounded stdout/stderr
draining, caller-controlled stdin, observer `Pending` waits, explicit
terminate, terminal snapshots, and reap. `tests/process/managed_process.rs` keeps all
public lifecycle tests outside the implementation; `run_managed_process` and
`rust-managed-process-bench` measure `process.managed.lifecycle` separately
from one-shot execution. The current release smoke measured roughly
707/1391/2761 ops/s at 1/2/4 workers, with p95 about 1.52/1.55/1.58 ms and
zero errors/rejections. Capacity is reserved before OS spawn so a full book
fails without creating a child. PTY, process-group termination, capability
authorization, ProcessTable registration, AgentLoop routing, and runtime
authority remain outside this candidate.

`BenchmarkEvidence` wraps a complete report with schema-versioned platform,
architecture, runtime, source-revision, and runner metadata. Its JSON
round-trip validates the metadata, resource units, and worker/round coverage
before export or ingestion. `make rust-benchmark` runs the release-mode queue
smoke and prints one evidence document; `make r2-baseline-bundle` runs that
Rust producer plus the independent Python reference and writes a comparison
bundle. This is build/performance perimeter evidence only; it does not grant
runtime authority or imply a cutover decision. `make rust-worker-benchmark`
prints machine-readable WorkerPool-only fixed-work JSON; its queue capacity must cover
the batch, so eviction is reported as a benchmark configuration error rather
than silently counted as throughput.

The `state_queue` module is the first Rust-owned state/queue prototype: each
shard owns its slot map and lifecycle transitions, while `BoundedWorkQueue`
uses typed work items and fail-fast capacity rejection. Its consumer can drain
a bounded batch under one lock, reducing hot-path lock churn without changing
fixed-work accounting. A condition-variable `push_wait`/`pop_wait` mode is
available for explicit experiments, but remains opt-in because the R2 smoke
shows multi-worker convoy and tail-latency costs. Queue length and
accepted-but-not-completed metric depth are intentionally separate; the
prototype also exposes a token-aware wait that returns `Cancelled` before
claiming work. `ProcessHandleAllocator` adds bounded slot reuse with
generation-incrementing release and stale-handle rejection, but it does not
schedule tasks, replace ProcessTable storage, or own boot state.

The `scheduler` candidate composes that allocator, sharded state, and bounded
queue into a deterministic spawn/schedule/claim/complete/stop/reap boundary.
Queue-full admission rolls lifecycle state back, stopped queued work is
discarded on claim, and no worker threads, boot callbacks, or AgentLoop routes
are started.

The `runtime` module composes the locked assembly, lifecycle FSM,
`KernelScheduler` state ownership, and bounded WorkerPool into an explicit
Rust execution host. It boots only through the validated metadata boundary,
tracks submitted closure states, supports cancellation/deadlines, and drains
workers before clean shutdown. It deliberately does not own Python state,
PTY/subprocess providers, AgentLoop routing, prompt/tool policy, or the
production entrypoint. `open_persistent` binds the same execution host to a
fresh Rust `StateStore`, records clean lifecycle checkpoints, and requires an
explicit recovery path after an unclean close. `submit_gated` evaluates the
Rust G1-G5 chain before invoking the single CapabilityAuthority, so an empty
whitelist or unwired executor cannot enter the worker queue.

State-queue, process, managed-process, terminal, session, agent-loop, substrate, benchmark, health, territory, sync,
registry, identity-uid, swapper, tool-chain, schema, migration, capability,
cancellation, notify, reputation, audit, device, interrupt, errors, channel,
bus, registry-base, event, benchmark-runner, scheduler, runtime, and worker behavior
tests plus the protocol-host gate tests live in independent files under
`crates/l1-kernel-rs/tests/<domain>/`; `Cargo.toml` explicitly registers each
target and implementation modules retain no private fixture dependency for
those slices. The public contract-version check is also part of
`tests/protocol/contract_vectors.rs`, so the crate root has no inline test module. Value
contract behavior is isolated in `tests/protocol/contract.rs`.

Synchronization behavior is split between the public `tests/core/sync.rs` target
and the shared-vector `tests/core/sync_vectors.rs` target. The source module has no
inline tests; this keeps the Rust API boundary explicit for the later
clean-break runtime and TS-facing adapters.

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
integration/Python adapter tests freeze only authorization and mutation
lifecycle; prompt text, random UID bodies, and persistence bytes are
intentionally excluded. Mechanism tests are isolated in
`tests/policy/identity_binding.rs`.

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
configuration, starts workers, mutates lifecycle state, or wires the Python
boot registry. `tests/fixtures/kernel_boot_plan_vectors.json` is shared with
the Python adapter; the fixture records Python's intentional omission of
missing dependencies so the clean-break Rust boundary does not inherit it.

The `state_layout` module defines the first R4 state-ownership boundary. It
validates a versioned Rust-owned manifest with canonical relative entries and
declared parent directories, then maps host-supplied observations to explicit
`initialize`, `resume`, `recover`, `migrate`, or fail-closed `reject` actions.
It does not create directories, read files, import Python state, or run
migrations. `tests/fixtures/kernel_state_layout_vectors.json` is consumed by
the Rust integration test and a Python adapter-side reference test; the
future R4 owner will supply filesystem probes and side effects.
Manifest and decision invariants are also covered by the independent
`tests/storage/state_layout.rs` target.

The `state_store` module is the first filesystem-bearing R4 adapter. It creates
only the fresh Rust root described by `state_layout`, persists manifest and
lifecycle/checkpoint documents using per-file atomic rename plus `sync_all`,
and exposes clean-resume and unclean-recovery actions. It rejects divergent
or migration-required roots and never imports Python state.
The durable lifecycle/recovery behavior is exercised through the public
`tests/storage/state_store.rs` target.

The `ports` module now translates the mechanism-port value surface and
declarative registration boundary: `PortResult`, `Endpoint`, `Message`, and
privacy-preserving `InputActivitySnapshot` are validated without side effects,
while `PortRegistry` preserves registration order, rejects invalid/duplicate
names, and supports an explicit pre-wiring lock. It does not instantiate
transport, process, storage, scheduler, or input providers. The shared
`tests/fixtures/kernel_port_vectors.json` fixture covers values and descriptor
ordering for the future Rust adapter layer.

The `input_activity` module adds the T4a Rust/TS projection for that
privacy-preserving value. `InputActivityProbe` accepts only bounded,
host-injected source labels, permission states, aggregate keyboard/pointer
flags, and caller-supplied timestamps; it applies an explicit idle window and
returns the existing `InputActivitySnapshot`. Duplicate sources, future or
non-finite timestamps, unauthorized activity flags, and source-limit overflow
fail closed. It never opens device nodes or retains raw input. The shared
`tests/fixtures/kernel_input_activity_vectors.json` fixture is consumed by
Rust and TypeScript; real keyboard/pointer adapters remain host-owned and are
tracked separately as T4b.

The `assembly` module composes the validated boot plan, state layout, port
registry, and halted lifecycle into a `KernelAssembly` snapshot. The
`rust-kernel` binary is an independent no-Python entrypoint that requires an
explicit state-root argument and emits this snapshot as JSON. It is
deliberately declarative: it does not read config,
create the state root, execute boot callbacks, or instantiate providers. This
is the R4 assembly seam; `state_store` now owns fresh-root initialization and
durable recovery. Mechanism and shared-vector coverage live in
`tests/assembly/assembly.rs` and `tests/assembly/assembly_vectors.rs`.

The `preflight` module adds a read-only entry check above assembly. It requires
explicit `AssemblySpec` and host `StateProbe` values, then emits a versioned
snapshot with the selected state action and `Ready`/recovery/migration/reject
disposition. `rust-kernel-preflight` consumes one JSON request from stdin and
prints one JSON report; `make rust-kernel-preflight` builds it for automation.
The tool never probes or mutates the filesystem, executes boot callbacks,
rebinds processes, or selects a Python fallback. Its tests are isolated in
`tests/assembly/preflight.rs`, and the candidate does not imply R5 cutover.

The `entry` module adds an explicit one-shot coordinator above the persistent
runtime. `EntryRequest` requires the entry contract version, complete assembly,
runtime limits, and an operation. `inspect` opens the Rust-owned root and
returns the current recovery decision; `boot_once` requires an exact
`RecoverUnclean` decision acknowledgement when needed, boots the runtime,
captures the active snapshot, and performs a bounded clean shutdown before
returning. `rust-kernel-entry` reads a bounded JSON request from stdin, while
`make rust-kernel-entry` builds it. Invalid limits, stale acknowledgements, and
recovery without caller acknowledgement fail closed. This is an R4 entry
coordination candidate and smoke harness only; it does not select a production
default, execute Python/PTY/provider/AgentLoop work, or close the R5 cutover.

The `protocol` module closes the retained R4 wire boundary as a pure candidate:
it validates v1 envelopes and TS-neutral records, canonicalizes nested JSON,
applies optional-field defaults, strips unknown record fields, and supplies
bounded outbox/cursor values. `tests/fixtures/protocol_v1_records.json` is
consumed by `tests/protocol/protocol_vectors.rs`; HTTP/WS framing, L2 dispatch, clocks,
and runtime session ownership remain adapter responsibilities. Mechanism tests
for canonical envelopes, record filtering, and outbox replay live in
`tests/protocol/protocol.rs`.

The `protocol_host` candidate is a bounded JSONL canonicalization gate over
that protocol. `ProtocolHost` rejects frames above its explicit byte limit
before decoding, validates and recursively canonicalizes accepted v1 envelopes,
and returns structured failures without panicking. `rust-protocol-gate` is a
no-Python stdin/stdout smoke entrypoint: it emits only canonical valid frames
and writes rejected-line diagnostics to stderr. It does not dispatch commands,
execute intents, own sessions, or route AgentLoop work, so it is an R4 adapter
preflight rather than runtime authority.

The `config_store` module is the clean-break R4 configuration owner. It creates
a versioned JSON manifest with separate `config.json` and `settings.json`
documents, tracks monotonic revisions, and uses per-document atomic rename plus
`sync_all`. It resumes only a matching Rust root and rejects foreign/future
layouts; Python YAML/settings import, migration callbacks, provider wiring, and
engineering-debug policy remain outside the store.
`tests/storage/config_store.rs` covers manifest ordering, fresh-root revisions, foreign
roots, invalid keys, and future-document rejection through the public API.

The `terminal` module supplies the lower-layer substrate for future
AgentLoop-backed terminals. `TerminalBook` enforces unique terminal/session/
process bindings, stores generation-tagged `ProcessHandle` values internally,
and exposes only the retained raw process id in snapshots. It also enforces
explicit lifecycle terminality and bounded opaque stream mailboxes with
sequence and drop accounting. The registry uses hash lookup while snapshot
output is sorted at the wire boundary for deterministic ordering. Batch input,
output, and drain methods acquire one terminal record lock per batch and
preserve FIFO, sequence, capacity, and per-frame error semantics. `run_terminal_book` and
`run_terminal_book_batch` expose separate fixed-work v3 workloads through the
`rust-terminal-bench` and `rust-terminal-batch-bench` binaries; their latency
units are per-frame versus per-batch and must not be mixed. It does not own
PTYs, subprocesses, AgentLoop execution, prompts, tools, or frontend rendering;
`tests/fixtures/kernel_terminal_vectors.json` and the independent terminal
integration targets cover the Rust-only contract.

The current contract module mirrors process state/results/options, primitive
JSON values, signal/event records, EventBus counters, and the capability
request/result boundary. `tests/fixtures/kernel_value_vectors.json` is loaded
by both Python and Rust tests; JSON numbers retain integer versus fractional
wire shape. The isolated `sync` module contains candidates for Mutex,
Semaphore, Barrier, Condition, and RWLock; RWLock write depth and empty owner
rejection are part of the shared vector contract and are tested independently.
The shared `tests/fixtures/kernel_sync_vectors.json` additionally freezes
reentrant reads, zero-timeout writer failure, status snapshots, and missing-owner
unlock errors. The Rust candidate now assigns FIFO writer tickets, removes
expired tickets before waking successors, and keeps writer preference over new
readers without changing reentrant reads/writes. The standalone `cancellation`
module provides a cloneable one-way token, first-reason retention, cooperative
checks, and bounded waits; RWLock can remove a cancelled writer ticket before
waking successors. Task/queue cancellation, cross-process IPC ownership, the
named registry, deadlock-cycle reporting, and runtime routing remain pending
for the sync slice. The isolated `process`
module now mirrors PCB snapshots, lifecycle FSM transitions, cancellation,
resource accounting, and bounded process audit rows. The shared
`tests/fixtures/kernel_process_vectors.json` freezes PID/PCB registration,
READY/RUNNING transitions, cancellation terminality, exit-to-ZOMBIE and reap,
resource totals, identity verification, and timestamp-independent audit order.
`ProcessTable` also exposes a fail-closed typed-handle bridge for live PIDs,
handle lookup, exit, and reap; the parity table uses generation one while
reusable-slot ownership remains in `state_queue`.
Reaper scheduling, Python interrupt/allocator cleanup, long-lived OS handles,
and runtime routing remain Python-owned until a module-specific pilot is approved.

The isolated `event` module mirrors synchronous signal history, typed and
wildcard subscriptions, bounded callback delivery, submitted/completed/dropped
counters, shutdown draining, and bounded dynamic signal registration. It does
not own L3 event policy or SSE/WS fan-out. The shared
`tests/fixtures/kernel_event_vectors.json` freezes bounded history retention,
type filters, signal serialization, and idle dispatch counters; callback
scheduling and overload fairness remain outside the deterministic vector. The
Rust candidate now serializes callback execution per signal channel while
scanning past a busy channel, so a slow `TASK_ASSIGN` callback cannot reorder
the next `TASK_ASSIGN` or starve an unrelated `TASK_DONE` channel. This
ordering is tested as a Rust-native mechanism invariant; Python callback
timing remains reference-only.

The isolated `channel` module provides the JSON edge primitive used by a
future `ChannelPort`: fixed-capacity FIFO, timeout-aware put/get/peek,
overwrite-oldest mode, drain, utilization, and close semantics. Draining wakes
all producers when multiple slots become available. The shared
`tests/fixtures/kernel_channel_vectors.json` covers these values; socket,
transport, and AgentLoop routing remain outside the candidate.

The `constitution` module accepts explicit policy snapshots and evaluates only
pure rule values. Checked replacement rejects empty or duplicate IDs,
non-builtin/custom sources, and custom evaluators; tags are normalized for
deterministic export and failed replacement leaves the prior snapshot intact.
Markdown parsing, posture providers, and runtime policy routing remain outside
the Rust candidate. `tests/fixtures/kernel_constitution_vectors.json` covers
the custom-rule boundary; public mechanism tests are isolated in
`tests/policy/constitution.rs` and the vector target.

The isolated `platform` module mirrors provider-neutral OS values, shell and
grep command descriptions, URL joining, temporary-directory derivation, and
TCP endpoint parsing. It never executes commands, creates directories, or
opens sockets; those remain Python adapter responsibilities. Public behavior and
shared vectors are isolated in `tests/terminal/platform.rs`.

The isolated `paths` module mirrors deployment-mode selection, `PraxisPaths`
child-path derivation, explicit environment/config overrides, and a resettable
in-memory path store. `PathInputs` are injected by the host; environment
discovery, home-directory probing, and layout creation remain outside the
candidate. Public behavior and shared vectors are isolated in `tests/storage/paths.rs`.

The isolated `network` module provides caller-clocked `PeerBook` bookkeeping:
endpoint validation, self-announcement filtering, one-shot loss reporting,
grace-period eviction, and deterministic health/list views. Socket discovery,
TCP/UDP/TLS, EventBus delivery, card sync, and message envelopes remain
transport adapters. Its mechanism tests are split between `tests/network/network.rs`
and the shared `tests/network/peer_vectors.rs` target.

The isolated `boot` module provides declarative `BootPlan` metadata with
explicit replacement, pre-wiring lock, and deterministic dependency-first
ordering. It never executes callbacks or starts runtime services. Its
mechanism tests live in `tests/assembly/boot.rs`, alongside the shared vector target.

The isolated `discovery` module mirrors the three-tier configuration registry:
registered defaults and source snapshots, already parsed section overrides,
object shallow merge, scalar replacement, null-section default retention,
unknown-section ignore behavior, runtime key updates, and tool/service fallback
queries. `tests/fixtures/kernel_discovery_vectors.json` is consumed by both
languages. YAML parsing, discovery-directory scans, logging, boot registration,
and Python registry mutation remain adapter-owned; public behavior and shared
vectors are isolated in `tests/registry/discovery.rs`.

The isolated `load_adaptive` module mirrors the pure worker-sizing control law:
EWMA smoothing, hysteresis, target-band HOLD, bounded GROW/SHRINK and
GROW_FAST decisions, cooldown, reset, and explicit caller-supplied time.
`tests/fixtures/kernel_load_adaptive_vectors.json` is consumed by both
languages. Sampling, WorkerPort mutation, adaptive enablement, and worker
threads remain Python-owned.

Its mechanism tests live in `tests/core/load_adaptive.rs` as an independent
integration target; the source module exposes no inline test block.

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
Its public behavior tests live in `tests/policy/rule_descriptor.rs`.

The isolated `ports` module owns validated port values and deterministic
registration metadata for future adapters. It does not instantiate providers
or perform I/O; `tests/assembly/ports.rs` and `tests/assembly/port_vectors.rs` cover the public
value and registry boundary.

The isolated `registry_base` module mirrors the declarative metadata portion of
Python's `MapRegistry`: descriptor defaults, duplicate rejection or explicit
overwrite, registration order, category filtering, public serialization, and
registration/removal counters. `tests/fixtures/kernel_registry_base_vectors.json`
is consumed by both languages. Handler closures, domain-specific registries,
source discovery, and runtime routing remain adapter-owned.

The isolated `registry` module mirrors only name-sorted opaque JSON section
snapshots and explicit system-summary aggregation. The shared
`tests/fixtures/kernel_registry_vectors.json` covers healthy module counts,
process/device/syscall counts, and caller-supplied time. Section producers,
singleton queries, syscall discovery, clocks, and runtime registry ownership
remain Python-owned.

The isolated `tool_chain` module mirrors only stable call-field normalization,
HMAC-SHA256 fingerprint truncation, the `GENESIS` fallback, and root-first
chain verification. `tests/fixtures/kernel_tool_chain_vectors.json` is
consumed by both languages. Key provisioning, call storage, trimming,
re-rooting, and execution remain Python-owned.

Rust test ownership is fully isolated from implementation modules. Mechanism,
concurrency, public behavior, and cross-language parity tests all consume the
public API from `crates/l1-kernel-rs/tests/<domain>/` as independent integration
targets; `src/` must contain no `#[cfg(test)]` or inline test module. Cargo
implicit discovery is disabled so the Python infra gate
`tests/infra/test_rust_test_domain.py` can reject root-level or unregistered
targets. Shared JSON fixtures stay in `tests/fixtures/`; run the isolated
domain with `make rust-contract-test` or a bounded `cargo test --test <name>`.

The isolated `identity_uid` module mirrors the value-only UID issuer boundary:
prefix and body-length validation, bounded entropy candidates, collision
tracking, reset, and existing-UID restoration. The shared
`tests/fixtures/kernel_identity_uid_vectors.json` freezes these values. Random
entropy, persisted bindings, and identity authority remain Python-owned.

The isolated `device` module mirrors deterministic device bookkeeping:
explicit records, sliding-window rate checks, strict health thresholds, call
counters, summaries, and aggregate type/health stats. The shared
`tests/fixtures/kernel_device_vectors.json` supplies timestamps and policy
thresholds; SettingsCenter, provider connections, health threads, and system
clock access remain Python-owned.

The isolated `bus` module mirrors SystemBus metadata, registration replacement
in place, parent-available dependency filtering, stable Kahn planning, cycle
errors, and explicit component state labels. The shared
`tests/fixtures/kernel_bus_vectors.json` covers these values. Event handlers,
child-bus routing, health/stats providers, callbacks, and actual component
lifecycle ownership remain Python-owned.

The isolated `health` module mirrors explicit subsystem-result aggregation:
status precedence, healthy/degraded/failed counts, subsystem retention, and
elapsed-time rounding. The shared
`tests/fixtures/kernel_health_vectors.json` covers these values. Module
imports, clocks, singleton probes, logging, and runtime providers remain
Python-owned.

The isolated `swapper` module mirrors memory-ring planning only: importance
based ring-2/ring-3 routing, expired short-ring compaction filters, and
pressure action flags. `tests/fixtures/kernel_swapper_vectors.json` is shared;
MemoryService mutation, allocator sampling, clocks, background threads, and
persistence remain Python-owned.

The isolated `territory` module mirrors boundary-safe lexical subtree checks.
It accepts an explicit working directory for relative inputs, uses component
semantics to reject prefix collisions, and performs no filesystem or symlink
resolution. GateChain and Constitution consume the candidate helper; runtime
policy and adapter-owned path context remain in Python.

The isolated `interrupt` module mirrors the five Python IRQ kinds, per-kind
sequence counters, empty-payload normalization, and bounded recent history.
It records values behind a mutex but does not execute callbacks, emit signals,
replay persistence, or terminate processes; those effects stay with Python
adapters.

The isolated `errors` module mirrors the built-in error-code catalog, fallback
messages, Python-compatible failure responses, cause truncation, and explicit
trace propagation values. It does not resolve locales, inspect stacks, capture
to ErrorBus, or persist logs; those remain adapter responsibilities.

The isolated `channel` module mirrors the fixed-capacity `ChannelPort` ring for
JSON values: blocking put/get with deadlines, overwrite-oldest mode,
peek/drain, close wakeups, and utilization. Arbitrary Python objects and
transport framing remain outside the boundary.

The isolated `allocator` module contains configuration-injected allocator and
resource-limiter candidates for allocation/free accounting, expired/observe
reclamation, bounded OOM victim reclaim, pressure, swap accounting, profiles,
and cleanup. Interrupt delivery, process termination, and durable persistence
remain Python adapter responsibilities. Public mechanism and resource-vector
coverage are isolated in `tests/core/allocator.rs`.

The `ResourceLimiter` portion additionally consumes
`tests/fixtures/kernel_resource_vectors.json`, freezing injected profiles,
fallback lookup, signed check/release costs, usage snapshots, profile cleanup,
and arbitrary-resource release behavior. Python role configuration remains the
source of profile data; the Rust candidate does not own policy discovery.

The isolated `worker` module mirrors the bounded `WorkerPort` shape: minimum
and maximum resident workers, FIFO eviction of pending work under backpressure,
result handles, panic-to-error conversion, graceful draining, idle shrink to
the configured floor, pre-start cancellation through `TaskHandle`, and
caller-supplied task deadlines through `submit_result_with_timeout`. A cancelled
or expired queued task completes with a structured result and its closure is not
run; an already-running closure is not forcibly interrupted, and completion
after its deadline is reported as `TaskTimeout`. `TaskHandle::result` retains a
separate `Timeout` for the waiter's observation deadline. Tasks are already-
bound Rust closures returning JSON values; argument binding, adaptive sampling,
and Python exception mapping remain adapter responsibilities. `stats()` exposes
ordered outcome counters for cancelled, timed-out, and failed worker executions;
the counters are updated before a result handle is released so observations
cannot race ahead of their accounting. The counters and pool sizing/activity
gauges use atomics, leaving only the bounded task queue and worker-handle list
under mutexes; this removes the per-task metrics mutex from the hot path. The
public worker integration target also covers concurrent submission and checks
that completed plus evicted work equals the fixed submission count.
Completion notification uses the final active-counter transition; it does not
take a second queue lock merely to inspect emptiness after every task. Shutdown
still observes both queue depth and active count before joining workers. Workers
claim at most eight FIFO tasks per queue lock and reuse that bounded claim
buffer; the active gauge includes claimed-but-not-yet-completed tasks so
shutdown cannot observe a gap between two tasks in a local batch. This reduces
queue lock handoffs for small closures, but fixed-work release evidence still
shows lower throughput at two and four workers, so the batch size remains an
evidence-backed candidate rather than a scaling policy. `stats()` now exposes
the aggregate `queue_wait_ns` spent from a batch claim attempt until work is
claimed; `run_worker_pool_batch` carries that value into the v3 benchmark
sample instead of reporting a misleading zero. The latest 4096-item release
smoke measured roughly 1.0 ms, 19.7 ms, and 177.8 ms median claim wait for
one, two, and four workers respectively, confirming shared-queue handoff as
the current scaling bottleneck. Batch admission wakes at most the smaller of
the submitted count and resident worker count through repeated `notify_one`
calls, which bounds condition-variable convoy without changing FIFO or
shutdown semantics. This wake strategy is also evidence-backed candidate
behavior and does not grant WorkerPool runtime authority.

The isolated `ipc` module mirrors the lock IPC value and registry shape:
`LockMessage`, bounded `LockChannel` history, synchronous handlers,
request/response wakeups with timeout cleanup, and resettable `LockBus`
registration. It is an in-process candidate; socket transport and cross-process
ownership remain outside the boundary. Public mechanism coverage lives in
`tests/core/ipc.rs`.

The isolated `persist` module mirrors the append-only event-journal record and
query shape (`seq`, `event`, `payload`, `ts`), batch append, type filtering,
sequence checks, reopen recovery, and durable flush. It uses JSONL for the
candidate backend within one process; Python SQLite storage, multi-process
coordination, and replay policy remain adapter-owned. Filesystem-backed
mechanism coverage lives in `tests/storage/persist.rs` and uses temporary roots only.

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
authorizes a production call. Public mechanism and shared policy coverage live
in `tests/policy/gatechain.rs` and the policy vector target.

The isolated `constitution` module mirrors the pure rule layer: serialized
MUST/SHOULD/MAY descriptors, PASS/WARN/BLOCK results, action-category
prefiltering, territory/sandbox/constitution/scout/cross-territory checks,
GateChain markers, and explicit offensive-skill posture inputs. Markdown
parsing/rendering, custom-rule persistence, NMI/EventBus emission, and skill or
posture provider lookup remain Python/adapter responsibilities.

The isolated `vfs` module mirrors the provider-neutral L1 filesystem boundary:
bounded mount registration, longest-prefix resolution, ring/read-only checks,
virtual-file storage, provider-read caching with TTL and invalidation, and
structured `resolve_mount` metadata. Real files, `/proc`, `/sys`, `/skills`,
`/dev`, symlink policy, and provider writes remain outside Rust; non-virtual
operations return `EADAPTER` until a versioned adapter contract and rollback
pilot exist. Mount, virtual-file, cache, and shared-vector coverage are
isolated in `tests/storage/vfs.rs`.

The isolated `lifecycle` module mirrors the provider-neutral lifecycle FSM and
checkpoint record: halted/installing/booting/active/draining/crashed states,
validated transitions, boot/shutdown bookkeeping, install/recovery decisions,
and JSON encode/decode. It does not inspect the filesystem or persist a
checkpoint by itself; a Python-owned adapter remains responsible for durable
storage and boot wiring.

The isolated `versioning` module mirrors the six kinds currently registered by
Python (`snapshot`, `checkpoint`, `card_registry`, `todo_table`,
`transaction_area`, and `capability_gate`). It stamps primitive JSON objects,
applies ordered callbacks, and returns structured future/missing/failure
errors. The `migration` module mirrors the ordered install-time runner,
including duplicate target registrations in registration order, bounded target
selection, first-error stop, and panic-to-error conversion. Settings, provider
migrations, and runtime install authority stay Python-owned.

The versioning mechanism tests live in `tests/protocol/versioning.rs` as an independent
integration target; global registry reset is exercised only through its public
API.

`tests/fixtures/kernel_policy_vectors.json` is the shared parity source for
the GateChain and Constitution candidates. Rust and Python tests consume the
same block/pass cases; provider side effects and runtime routing are excluded
from the fixture by design.

`tests/fixtures/kernel_vfs_vectors.json` is the shared mount-resolution source
for the VFS candidate and Python reference. It freezes only stable prefix,
relative-path, root, ring, and read-only fields; provider I/O remains excluded.

`tests/fixtures/kernel_lifecycle_vectors.json` and
`tests/fixtures/kernel_versioning_vectors.json` are shared parity sources for
the lifecycle and schema candidates. They freeze only deterministic state,
JSON, and error fields; timestamp generation, filesystem persistence, and
migration side effects remain adapter-owned. Lifecycle mechanism tests are
isolated in `tests/core/lifecycle.rs`.

```bash
cargo test --workspace --manifest-path crates/Cargo.toml
cargo fmt --manifest-path crates/Cargo.toml --all -- --check
cargo clippy --manifest-path crates/Cargo.toml --workspace --all-targets --all-features -- -D warnings
```
