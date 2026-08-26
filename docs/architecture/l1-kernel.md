# L1 — Kernel Layer

The bare-metal kernel: what every upper layer builds on. 69 files /
18,635 lines; 1,213 constants across 8 `params/` modules (mechanism-only —
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
| `params/*` | 1,213 compile-time constants — mechanism-only after WS5.4 (kernel/allocator/sync/gatechain/tool/system); business constants live in `l3/params.py` (agent/card-gate/review/scout) and `l4/params.py` (API/eval/diff/security-gate) |


## Kernel surface boundary (Rust readiness)

The kernel’s semantic surface is frozen for the Rust rewrite (`l1_kernel_rs`):
security/control invariants and explicitly retained wire fields are evidence;
Python class layout and user-data formats are not migration requirements.

The staged Rust build boundary lives in `crates/l1-kernel-rs/`. Its primitive
value contracts are mirrored and isolated mechanism candidates now cover
sync/cancellation/process/event/channel/allocator/worker, lock IPC, journal, bounded audit,
capability-authority, G1-G5 gatechain, Constitution rule/evaluation shapes,
provider-neutral VFS mount/cache mechanics, platform value/command descriptions,
deployment path derivation, lifecycle FSM, schema versioning, ordered migration
runner, pure load-adaptive control law, metadata-only registry base and summary,
deterministic device bookkeeping, explicit health-result aggregation,
memory-ring swap planning, and tool-call fingerprint chaining, but it remains
candidate-only until a
fixed-work performance evidence, semantic invariant vectors, and a
cutover/recovery decision; the preflight branch keeps the Python kernel as its
runtime implementation until the independent Rust build reaches R4/R5.

The Rust-first R1 substrate now provides generation-tagged process handles,
deterministic shard planning, and allocation-free atomic queue metrics. These
are ownership and measurement primitives only; they do not start scheduling,
replace ProcessTable storage, wire boot, or grant runtime authority.

The Rust `benchmark` candidate defines the fixed-work R2 report shape and
rejects incomplete work, unknown worker counts, duplicate/out-of-range rounds,
zero-duration samples, invalid p95/p99 ordering, invalid resource availability,
and unsupported schema versions. Schema v3 records p95/p99 tail latency,
aggregate queue/lock waits, rejected work, and process CPU/RSS deltas.
Throughput is derived from fixed completed work and elapsed time via
`BenchmarkSample::throughput_ops_per_sec`; resource units are nanoseconds and
bytes with explicit source metadata.

The Rust `benchmark_runner` candidate measures a fixed total through a bounded
typed queue for each worker/round pair, samples process resources, and drains
the queue before emitting a complete v3 report. It is a contention/stress smoke
only; it does not start scheduling, replace ProcessTable storage, wire boot, or
grant runtime authority. Bounded drain completion uses one atomic counter update
and saturating queue-depth CAS per batch, without changing fixed-work totals.

The same module exposes separate `run_worker_pool_batch` and
`run_worker_pool_batch_submit` workloads. The `rust-worker-bench` and
`rust-worker-batch-submit-bench` release binaries keep queue capacity at or
above the fixed batch, record WorkerPool submission p95/p99 plus batch
throughput, and reject configurations that could evict work. The batch-submit
candidate groups admission under one queue lock and keeps its evidence
separate from both `worker.pool.batch` and `substrate.queue.contention`.
Repeated local release samples completed all 4096-item work with zero
errors/rejections; at the same 1/2/4-worker sweep, batch-submit medians were
about 1.66M/3.85M/4.19M ops/s versus 1.20M/0.28M/0.07M for per-task
admission, with lower aggregate queue wait. This is evidence for the
admission optimization, not a runtime cutover decision.

`BenchmarkEvidence` is the versioned export envelope for this report. It binds
the complete worker/round matrix to platform, architecture, runtime, source
revision, runner, and resource-unit metadata and rejects invalid or incomplete
JSON on both construction and ingestion. `make rust-benchmark` emits one
release-mode evidence document; `make r2-baseline-bundle` combines it with the
independent Python reference under the same fixed-work contract. These are
build/performance artifacts and do not replace runtime authority.

The `state_queue` candidate gives each shard ownership of its slot map and
lifecycle transitions, and uses typed work items with fail-fast capacity
rejection. Queue length and accepted-but-not-completed metric depth remain
separate measurements. An opt-in token-aware pop returns `Cancelled` before
claiming work, using a bounded poll interval; task scheduling, queued-item
invalidation, boot state, and runtime routing stay outside the candidate.

The Rust `scheduler::KernelScheduler` candidate now composes the process-handle
allocator, sharded state, and bounded queue. It owns only deterministic
spawn/schedule/claim/complete/stop/reap transitions: queue-full admission rolls
back to READY, stopped queued items are completed as discarded, and stale or
reaped handles fail closed. It does not start workers, execute boot callbacks,
or route AgentLoop sessions.

The `worker` candidate now connects `TaskHandle` to the cancellation token and
supports caller-supplied task deadlines through `submit_result_with_timeout`:
queued work can complete with a structured `Cancelled` or `TaskTimeout` result
before its closure starts, while an already-running closure is never forcibly
interrupted. A running closure that returns after its deadline is marked
`TaskTimeout`; the handle waiter's own observation deadline remains the separate
`Timeout` error. Adaptive sampling, argument binding, and WorkerPort/runtime
ownership remain outside the candidate. The worker snapshot also exposes
cancelled, timed-out, and failed execution outcome counters, updated before the
corresponding result handle is notified.

Worker metrics are Rust atomics rather than a process-wide metrics mutex:
submission rejection, active/completed/outcome counters, and pool-size changes
avoid serializing every task on one accounting lock. The bounded task queue and
worker join list remain mutex-owned. The independent `tests/core/worker.rs` target
exercises concurrent submission and verifies that completed plus evicted work
matches the fixed submission count.
The completion path also relies on the last active-counter transition to wake
drainers, eliminating a redundant post-task queue lock while preserving the
queue-depth plus active-count shutdown condition. A worker claims at most eight
FIFO tasks per queue lock and reuses a bounded local buffer; `active` includes
claimed-but-not-yet-completed tasks so shutdown cannot pass through a local-batch
gap. The release fixed-work smoke still reports zero errors/rejections but
lower two/four-worker throughput for trivial closures, so this is a measured
handoff candidate rather than a promoted scaling policy. `WorkerPool::stats()`
also reports aggregate `queue_wait_ns` from each batch claim attempt through
successful work claim, and the WorkerPool benchmark carries it into the v3
sample. The latest fixed 4096-item release smoke measured median claim waits of
about 1.0 ms, 19.7 ms, and 177.8 ms at 1/2/4 workers, making shared-queue
handoff contention explicit rather than leaving the field at zero.

`WorkerPool::submit_result_batch` admits a caller-supplied group while holding
the queue lock once. It returns one `TaskHandle` per closure, applies the same
oldest-pending eviction and closed-pool failure completion to every item, and
retains the existing cancellation/deadline execution boundary. The independent
worker integration target covers FIFO ordering, per-item eviction accounting,
and closed-pool completion for this candidate. Batch admission wakes at most
`min(submitted, resident_workers)` waiters with repeated `notify_one` calls
instead of broadcasting to every worker; this bounds condition-variable convoy
without changing FIFO claim order or shutdown semantics. It remains a measured
candidate and must be rechecked through the same v3 fixed-work matrix before
any runtime policy promotion.

The Rust `agent_loop` candidate is the logical routing seam above the session
and terminal substrates. `AgentLoopBook` validates agent/cell/session/terminal
correlation, owns an explicit Created/Ready/Running/Paused/Closing/Stopped/
Failed lifecycle, and admits input/events while holding a shared lifecycle
read lock across the SessionBook write. Lifecycle writers use the exclusive
lock, so pause/stop wait for in-flight admissions before changing state while
same-loop admissions no longer serialize on one mutex. Session
history and `input_seq` remain authoritative in `Session`; terminal mailboxes,
PTYs, subprocesses, providers, prompts, tools, and worker execution remain
adapter-owned. The candidate is covered by the independent
`crates/l1-kernel-rs/tests/session/agent_loop.rs` target and does not grant runtime
authority. `run_agent_loop` and `rust-agent-loop-bench` add a separate v3
fixed-work input-admission workload with lifecycle-lock wait accounting; a current
4096-item release smoke measured median throughput of about 1.706M/0.898M/
0.724M ops/s and median lock waits of 0.098/3.919/16.045 ms at 1/2/4 workers,
with zero errors/rejections. With the contention-only probe, the latest
unpinned release median is about 1.819M/0.761M/0.760M ops/s and
0/5.011/13.583 ms of contended wait at 1/2/4 workers. A subsequent
read-lock/atomic-counter slice allows concurrent admissions and keeps the same
fixed-work contract; one local release sample measured about 2.49M/2.18M/0.90M
ops/s with p95 0.23/0.59/10.65 us and zero errors/rejections. These are
host-local observations, not a worker-scaling or cutover decision.
The lock-wait counter is contention-only: an uncontended `try_read`/`try_write`
path avoids
the timestamp and atomic accumulation, while a blocked acquisition records the
fallback wait. This keeps the metric useful for scaling evidence without
adding the full timing cost to every admission.
`AgentLoopHandle::admit_input_batch` and the book wrapper provide a grouped
admission candidate with one lifecycle read lock per input group. Results remain ordered,
Session keeps authoritative `input_seq`, and failed items increment failure
accounting without consuming command sequences. `run_agent_loop_batch` and
`rust-agent-loop-batch-bench` use workload `agent.loop.batch_admission` and
report batch p95/p99 separately from the per-input baseline; this is an
optimization slice only and does not grant runtime authority.

The `agent_loop_execution` module adds the next explicit execution seam:
`AgentLoopExecutionBridge` submits a caller-owned `AgentLoopAction` to the
bounded `KernelRuntime` worker pool. The task admits input only after worker
admission succeeds, passes the authoritative receipt and loop identity to the
action, and optionally admits one returned event. Its report and failure value
are versioned and include the completed input receipt, event receipt, failure
stage, and any partial input admission. Cancellation before execution leaves
the session untouched; action/provider work remains caller-owned, and the
bridge does not infer prompts, tools, PTYs, or production cutover policy.
The independent `tests/runtime/agent_loop_execution.rs` target covers success,
identity/state preflight, cancellation, and structured action failure.

The Rust `runtime::KernelRuntime` candidate composes the locked assembly,
lifecycle FSM, `KernelScheduler` state ownership, and bounded WorkerPool into a
single explicit execution host. It validates halted-to-booting-to-active
startup, assigns opaque handles to submitted closures, tracks terminal task
states, supports cooperative cancellation and task deadlines, and drains the
worker pool before a clean shutdown. The candidate has no Python/FFI bridge,
PTY or subprocess ownership, AgentLoop routing, provider callbacks, prompt or
tool policy, or default-entrypoint authority; those remain R4/R5 cutover work.
`open_persistent` attaches the Rust-owned `StateStore` to the same lifecycle,
durably records fresh-root boot and clean shutdown, and converts an unclean
root into an explicit recovery boot; it never imports Python state.
`submit_gated` is the only capability-shaped runtime submission helper: it
requires matching caller/tool identities, evaluates Rust G1-G5, and then calls
the single `CapabilityAuthority`; an empty whitelist or unwired executor stays
fail-closed and audited.

`KernelRuntime` now owns the Rust execution metadata books used by the future
clean-break entry: `SessionBook`, `TerminalBook`, and `AgentLoopBook`. A
persistent runtime opens the separate `ExecutionStore` under the same
Rust-owned root and restores only its validated metadata; an unclean document
returns crashed sessions, failed loops, and unbound created terminals. The
explicit `checkpoint_execution(false)` API supports caller-owned unclean
checkpoints, while a persistent `shutdown` writes the clean execution
checkpoint before marking the lifecycle halted. A clean checkpoint failure
keeps the lifecycle fail-closed and does not claim a successful shutdown.
These accessors expose lower-layer state to a future TS bridge without moving
AgentLoop execution, provider/tool policy, PTY ownership, or production entry
authority into the candidate.

The separate `recovery` module provides a pure `RecoveryTrigger` decision over
the validated execution document and lifecycle state: `fresh`, `resume_clean`,
`recover_unclean`, or `reject`. `KernelRuntime::recovery_decision` exposes this
decision without mutating books or booting workers. An unclean decision remains
a caller-owned gate for session recovery and terminal/process rebind; it is not
an implicit cutover or Python fallback selector. Persistent runtimes retain this
decision as a boot gate: `boot` rejects `recover_unclean` and inconsistent
(`reject`) roots until the caller acknowledges the exact decision generation.
Acknowledgement is in-memory and side-effect-free; it does not fabricate a
process/PTY binding or make TS/L2 the recovery authority.

Runtime submission uses a direct scheduler path when the WorkerPool already owns
the worker queue: `dispatch_direct`, `complete_direct`, and `stop_direct` preserve
generation-safe scheduler state without double-counting queue admission. Terminal
worker failures observed before the wrapper runs (for example, FIFO eviction or
shutdown rejection) are reconciled by `RuntimeTask::result()` so the task can be
reaped instead of remaining in `Running`. This is measured candidate behavior,
not production runtime authority.

Runtime admission now holds a shared lifecycle barrier across the active-state
check, scheduler reservation, shard-local task registration, and WorkerPool
handoff. Boot holds the exclusive side; shutdown first publishes `Draining`
and then holds it while already-admitted submissions drain. Registration precedes
`dispatch_direct`, so a fast closure cannot publish a terminal state and then
be overwritten by a late `Ready` insertion. The runtime task book uses the
same configured shard count as scheduler state, avoiding one global task-map
lock for unrelated handles. `submit_observed` is benchmark-only: its
contention-only `try_read` and task-book `try_lock` fallbacks expose aggregate
admission wait without timestamps or atomic updates in the normal submit path.
`run_runtime` and `rust-runtime-bench` measure a separate
`runtime.submit_reap` workload: each caller submits one bound `Value::Null`
closure, waits for completion, and reaps it before taking another task.
The aligned Linux x86_64 release sample on `06e8288c` completed all 4,096
items in each 1/2/4-worker, three-round case with zero errors and rejections.
Median throughput was about 18.1k/27.3k/32.1k operations/s; p95/p99 were about
85/140, 232/562, and 600/1,342 microseconds. Aggregate WorkerPool claim/wake
wait was 155.2/262.8/469.7 milliseconds per round, while median contended
runtime-admission wait was zero. This identifies WorkerPool handoff and tail
behavior, rather than runtime admission serialization, as the next candidate
bottleneck. The unpaired host sample is evidence only: it does not promote a
scaling policy or grant L2/TS, AgentLoop, provider, PTY, or production-entry
authority.

`KernelRuntime::reap_finished` adds a bounded caller-driven reaper seam. It
selects at most the requested number of task handles, releases only tasks
already in a terminal runtime state, and reports pending, unavailable, and
scheduler-error outcomes without blocking on live work. A zero budget is
rejected; the method does not start a background thread, change lifecycle
state, or claim production shutdown authority.

`submit_batch` reserves and registers every process handle before one grouped
WorkerPool handoff; an incomplete reservation rolls back every earlier handle
before a closure can execute. `run_runtime_batch` and
`rust-runtime-batch-bench` measure the separate
`runtime.batch_submit_reap` workload. Each caller admits at most one bounded
group, waits for all of its tasks, and reaps every handle before its next group;
the configured process and queue capacities cover the maximum in-flight groups
so eviction is not part of the experiment. The v3 completed-work and throughput
units remain tasks, but p95/p99 are explicitly per complete batch and therefore
are not compared directly with the single-task latency distribution. One local,
unpinned Linux x86_64 release sweep on the aligned tree with batch size 32
completed each 4,096-item 1/2/4-caller, three-round sample with zero
errors/rejections. Median throughput was about 363k/540k/591k tasks/s; median
per-batch p95/p99 were about 151/218, 217/290, and 442/586 microseconds;
aggregate WorkerPool claim/wake wait was 5.4/8.7/18.7 milliseconds and
observed runtime lock wait was 0/0.086/0.045 milliseconds. A separately
collected single-task sweep from the same aligned tree measured about
18.1k/27.3k/32.1k tasks/s and 155.2/262.8/469.7 milliseconds of queue wait.
The comparison is host-local evidence for retained grouped admission, not a
scaling, tail-latency, L2/TS, AgentLoop, provider, PTY, or cutover decision.

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

The locked plan also exposes an explicit `BootPlan::execute` seam. It requires
an exact caller-supplied handler for every step, validates the complete handler
set before invoking the first callback, and returns the completed prefix when a
handler fails or panics. The executor does not discover handlers, roll back
side effects, advance lifecycle state, or grant production boot authority;
those policies remain with the host.

The Rust `state_layout` candidate starts the R4 state-ownership boundary. It
validates a versioned manifest for a fresh Rust state root, canonical relative
entries, and declared parent directories. Given explicit host observations it
returns `initialize`, `resume`, `recover`, `migrate`, or fail-closed `reject`.
It does not inspect the filesystem, create directories, import Python state,
or execute migration callbacks. The shared
`kernel_state_layout_vectors.json` fixture freezes only the manifest and
decision values; a future R4 adapter owns probes and side effects.

The Rust `state_store` candidate is the first filesystem-bearing R4 adapter.
It creates only the fresh Rust root selected by the validated manifest, writes
manifest/lifecycle/checkpoint documents through `sync_all` plus atomic rename,
and exposes clean resume and unclean recovery. Divergent or
migration-required roots fail closed; Python state and Python boot authority
never cross this seam.

The Rust `ports` candidate translates the mechanism value surface and adapter
discovery metadata. `PortResult`, `Endpoint`, `Message`, and the
privacy-preserving `InputActivitySnapshot` are validated without I/O, while
`PortRegistry` provides deterministic registration order, duplicate rejection,
explicit replacement, and a pre-wiring lock. It does not instantiate provider
implementations or execute process, storage, transport, scheduler, worker, or
input activity operations. `kernel_port_vectors.json` freezes only these
values and metadata; provider side effects remain an R4 adapter concern.

The Rust `input_activity` candidate is the T4a value projection above that port.
`InputActivityProbe` consumes only bounded host-injected source labels,
permission states, aggregate keyboard/pointer flags, and caller time. It
applies an explicit idle window, rejects duplicate sources and invalid/future
timestamps, and emits the existing `InputActivitySnapshot` without opening
device nodes or retaining raw input. `kernel_input_activity_vectors.json` is
the shared Rust/TypeScript fixture; platform keyboard/pointer adapters and
permission prompts remain host-owned. T4b remains open for platform-specific
adapters, permission UX, and privacy/failure evidence; this value projection
does not grant hardware or runtime authority.

The Rust `assembly` candidate composes the boot plan, fresh state manifest,
Rust-owned config manifest metadata, retained protocol metadata, terminal
substrate metadata, port metadata, and halted lifecycle into a deterministic
`KernelAssembly`. `crates/l1-kernel-rs/src/bin/rust-kernel.rs` is an independent
entrypoint that requires an explicit state-root argument and emits this
complete snapshot as JSON with no Python import; it never infers a relative
working-directory root.
Assembly rejects config-contract, protocol, terminal-contract, and divergent
metadata before provider wiring. The entrypoint does not read configuration,
create directories, run callbacks, or instantiate providers. `state_store`
owns fresh-root initialization and durable lifecycle recovery; versioned
protocol serving and terminal I/O remain outside this assembly candidate.

The Rust `preflight` candidate adds a read-only R4 entry boundary above that
assembly. `PreflightRequest` requires an explicit `AssemblySpec` and host
`StateProbe`; `inspect` returns the validated assembly snapshot, state action,
and a coarse `Ready`/`RecoveryRequired`/`MigrationRequired`/`Rejected`
disposition. `rust-kernel-preflight` reads one JSON request from stdin and
emits one JSON report, while refusing malformed or incompatible input. It does
not probe the filesystem, create state, execute boot callbacks, start workers,
rebind processes, or select a Python fallback. This is operator and automation
evidence for R4 assembly, not Rust production-entry or R5 cutover authority.

The Rust `entry` candidate is the explicit coordinator above persistent
runtime state. `EntryRequest` requires a version, complete assembly, JSON-safe
runtime limits, and an operation. `inspect` reports the current recovery
decision without booting; `boot_once` accepts only an exact current
`RecoverUnclean` acknowledgement when recovery is required, then boots,
captures the active snapshot, and cleanly shuts down within the caller's
timeout. `rust-kernel-entry` is a bounded JSON stdin/stdout smoke entrypoint.
It never chooses a Python fallback, scans host terminals, runs providers or
AgentLoop work, fabricates process/PTY bindings, or changes the production
default. The independent `tests/runtime/entry.rs` target covers fresh, clean,
unclean, stale-acknowledgement, and invalid-config paths; R5 cutover remains
open.

The Rust `protocol` candidate now closes the retained R4 wire boundary without
granting runtime authority. It validates v1 envelopes and TS-neutral record
schemas, recursively canonicalizes JSON, removes unknown record fields for
forward compatibility, and provides bounded `Outbox`/`SessionCursor` replay
values. HTTP/WS framing, L2 dispatch, clock ownership, and session state remain
adapter-owned; `protocol_vectors.rs` consumes the existing shared record
fixture, so this is a versioned boundary proof rather than a Python state
migration layer.

The Rust `protocol_host` candidate adds the next R4 adapter seam: a bounded
JSONL canonicalization gate that rejects oversized frames before decode, invokes
the retained v1 validator, and returns canonical valid envelopes or structured
failures. `rust-protocol-gate` is a no-Python stdin/stdout smoke entrypoint; it
only emits accepted canonical frames and reports rejected lines to stderr. It
does not dispatch commands, execute intents, own sessions, or route AgentLoop
work, and its public behavior is tested in the independent
`tests/protocol/protocol_host.rs` target.

The Rust `config_store` candidate closes the configuration half of the R4
ownership boundary. It creates a fresh JSON-only Rust root with a versioned
manifest, separate kernel-config and runtime-settings documents, monotonic
revisions, and per-document atomic rename plus `sync_all`. Missing, foreign,
divergent, or future roots fail closed; `praxis.yaml`, Python settings,
engineering-debug policy, and provider wiring remain outside this store.

The Rust `terminal` candidate is the lower-layer substrate for future upper
layer AgentLoop terminals. `TerminalBook` owns unique terminal/session/process
bindings and stores generation-tagged `ProcessHandle` values internally;
snapshots expose only the retained raw process id wire field. It also owns
explicit created/ready/running/stopped/closed lifecycle states and bounded
opaque input/output mailboxes with sequence numbers and drop counters. Stopped
terminals cannot restart, closed terminals cannot be rebound, and mailbox
overflow or oversized frames fail closed. PTY/subprocess ownership, AgentLoop
execution, prompt/tool policy, rendering, and frontend multiplexing remain
adapter or L2/L3 responsibilities; `kernel_terminal_vectors.json` tests this
candidate in the independent Rust integration domain. The registry uses hash
lookup and sorts only the public snapshot view. Normal mailbox operations use a
read-locked registry plus a per-terminal record lock; batch submit/drain APIs
hold that record lock once while preserving FIFO, sequence, bounded-capacity,
and per-frame error behavior. `run_terminal_book` and `run_terminal_book_batch`
provide separate v3 fixed-work evidence (`terminal.book.mailbox` versus
`terminal.book.batch_mailbox`) with per-frame and per-batch latency units; this
is an optimization candidate, not PTY or runtime authority.

The Rust `session` candidate is the next P0 session-truth seam for the future
AgentLoop/TS bridge. A sharded `SessionBook` admits unique identities without a
global registry lock, while each `Session` owns bounded history, authoritative
user `input_seq`, monotonic message sequences, cursor paging, explicit
created/active/closing/closed/crashed lifecycle, and versioned checkpoint
values. Duplicate IDs, invalid cursors, over-capacity history, and inconsistent
snapshots fail closed. It does not execute prompts/tools, own PTYs, or route
AgentLoop work; its behavior is covered by independent `tests/session/session.rs` and
`tests/session/session_vectors.rs` targets.

The Rust `session_store` adapter closes the first durable P0 session boundary.
It atomically persists the deterministically ordered `SessionBook` collection
under `snapshots/sessions/checkpoint.json`, rejects unsupported versions and
duplicate identities, and refuses a clean write while any session is active or
closing. An unclean document is loaded as explicit `crashed` sessions so the
caller must recover and reactivate them before accepting input. The adapter
uses only the fresh Rust state root; it does not import Python state, replay
AgentLoop work, or grant runtime authority. Its behavior is covered by the
independent `tests/session/session_store.rs` target.

The `execution_store` adapter extends this durable boundary to the metadata
books needed by the future terminal-backed AgentLoop bridge. It atomically
checkpoints sessions, terminals, and logical loops under
`snapshots/execution/checkpoint.json`, validates sorted identities and
cross-book references, and never persists queued terminal bytes or live
process ownership. Clean writes reject writable sessions, active loops,
active terminals, pending mailbox frames, or process bindings. Unclean writes
normalize sessions to `crashed`, active loops to `failed`, and active terminals
to unbound `created` records so a later adapter must explicitly recover and
rebind them. `TerminalBook::restore` and `AgentLoopBook::restore` accept only
these safe metadata states. Coverage is isolated in `tests/session/execution_store.rs`;
this is an R4/R5 recovery seam, not boot or runtime authority.

The session hot path keeps hash indexes for message-id duplicate checks and
sharded session admission, then sorts only the public snapshot view so wire
ordering remains deterministic. `benchmark_runner::run_session_book` and the
`rust-session-bench` release binary exercise a fixed total of
create/activate/input operations under the v3 evidence schema, including
throughput, p95/p99, CPU/RSS, and explicit zero rejection/error counts. This
workload has no queue boundary, so queue wait remains zero. Its lock-wait
field accumulates only `try_write` fallbacks when a registry lock is unavailable,
without adding clocks to the public admission fast path; it does not authorize
runtime cutover.
The isolated 2026-08-23 Linux x86_64 release run recorded median admission
throughput of about 1.62M/1.46M/1.37M ops/s and median blocked-write wait of
0/0.85/3.32 ms at 1/2/4 workers, respectively. The declining write scale is
therefore an observed baseline for the separately measured batch/shard work,
not a claim that reader concurrency improves write admission.

The shared `snapshot::BookSnapshotPage` boundary now gives `SessionBook`,
`AgentLoopBook`, and `TerminalBook` a bounded, identity-ordered read API. A
bounded max-heap retains at most `limit + 1` handles while selecting from the
registry's hash/ordered indexes and only sorts that retained set before
constructing returned snapshots; limits are fail-closed in `1..=512`. The next
cursor is an exclusive logical identity, not a repeatable-read token, so
concurrent writes may alter later pages. Complete `snapshots()` calls remain
deterministic and unchanged for durable checkpoint validation, recovery, and
other complete-state consumers.

`SessionBook` uses shard-local `RwLock` registries: admission and removal
remain exclusive, while lookup and the complete/page read paths admit
concurrent readers. `rust-session-snapshot-page-bench` exercises 4,096 fixed
page requests against 4,096 prebuilt sessions at 1/2/4 workers for three
rounds under the v3 evidence schema. The benchmark records per-page p95/p99,
CPU/RSS, rejection/error counts, and aggregate read-lock wait only after an
initial `try_read` reports the registry lock unavailable; normal public pages do not pay
that timing cost. Two alternating Linux x86_64 release suites pinned to CPUs
0-3 compared the former bounded-tree selector with the max-heap candidate on
the same 4,096-record, 64-item-page, 4,096-request workload. The three-round
run medians were 17.8/18.0k versus 20.4/19.5k pages/s at one worker,
31.4/32.4k versus 35.1/37.1k at two, and 62.4/58.6k versus 63.9/70.1k at
four, respectively. Every paired run completed with zero rejects, errors, and
measured read-lock wait. The four-worker p95 varied between the paired suites,
so the evidence supports retained-throughput improvement only, not a stable
tail-latency claim. This is not a Python-host comparison, a writer-contention
guarantee, or runtime-cutover authority.

The companion `session.book.snapshot_page_write_contention` runner keeps one
single-shard book and makes each fixed work item verify the leading 64-item
page before admitting one unique session. Two alternating release suites
pinned to CPUs 0-3 completed all 4,096 bundles with zero rejects/errors. Their
worker medians were 12.2/13.1k, 14.1/15.4k, and 13.2/12.8k bundles/s at
1/2/4 workers; aggregate blocked lock wait was 0 ms, 142-164 ms, and
756-772 ms, while p95 bundle latency was 0.10-0.12 ms, 0.28-0.33 ms, and
0.89-0.93 ms. The 4-worker plateau and rising wait make the read/write
interaction explicit: the page read optimization does not establish a write
scaling policy. This workload is a mechanism-only contention baseline and
does not authorize AgentLoop, provider, persistence, or runtime cutover.

To reduce that read-lock hold time, each `SessionBook` shard now maintains a
private `BTreeSet` identity index beside its hash map. Duplicate admission and
direct lookup stay hash-backed, while a page reads at most `limit + 1` eligible
identities from the ordered set and then resolves those handles in the map;
create, batch admission, restore, and closed removal update both structures
under one write lock. A same-host hash-only reference release run measured
about 1.34/1.33/1.34M `session.book.admission` ops/s at 1/2/4 workers, while
the ordered-index candidate measured about 0.87/1.11/1.21M in one pinned
suite. The write-only cost is therefore material and remains an explicit
tradeoff. In the paired read/write workload, however, the candidate reached
about 61.7-66.4k/70.1-82.3k/55.9-57.5k bundles/s and reduced aggregate lock
wait to 0/14-19/123-127 ms at 1/2/4 workers. These are fixed-host mechanism
samples, not a stable production scaling or cutover decision.

`AgentLoopBook` and `TerminalBook` now apply the same bounded traversal rule
with private `BTreeSet` identity indexes beside their hash maps. Registration
and checkpoint restore update the hash and ordered structures under the same
registry write lock; direct lookup and complete `snapshots()` behavior remain
unchanged. The independent `agent_loop.book.snapshot_page` and
`terminal.book.snapshot_page` runners use the standard 4,096-record,
4,096-request, 1/2/4-worker, three-round v3 matrix. Their benchmark-only
`snapshot_page_with_lock_wait` path measures a clock only after `try_read`
reports contention; the public page API remains uninstrumented. One Linux
x86_64 release suite pinned to CPUs 0-3 recorded median throughput of about
54.2k/107.7k/207.3k pages/s for AgentLoopBook and
114.6k/190.8k/297.9k pages/s for TerminalBook at 1/2/4 workers, with zero
rejects, errors, and observed read-lock wait. These are single-host mechanism
baselines with no old-implementation A/B, writer contention, or runtime
cutover authority.

`SessionBook::create_batch` provides a separate grouped-admission candidate:
validated session specs are grouped by shard, each shard lock is acquired once,
and results retain input order with per-item duplicate/validation failures.
`session.book.batch_admission` and `rust-session-batch-bench` measure batch
latency separately from the per-session workload, so p95/p99 comparisons do
not mix admission units.

The state-queue, process, terminal, session, agent-loop, substrate, benchmark, health, territory, sync,
registry, identity-uid, swapper, tool-chain, schema, migration, capability,
cancellation, notify, reputation, audit, device, interrupt, errors, channel,
bus, registry-base, event, benchmark-runner, scheduler, runtime, worker, network,
rule-descriptor, boot, ports, identity-binding, state-layout, state-store,
config-store, platform, paths, discovery, lifecycle, assembly, contract, ipc,
persist, protocol, protocol-host, constitution, gatechain, allocator, vfs, load-adaptive, and
versioning mechanism
tests are maintained as
independent integration files under
`crates/l1-kernel-rs/tests/<domain>/`; the public contract-version check is also part of
`contract_vectors.rs`. Their public APIs are therefore the only test-visible
boundary for these slices.

The synchronization mechanism tests are also fully isolated under
`crates/l1-kernel-rs/tests/core/sync.rs`; the shared RWLock vectors remain in
`sync_vectors.rs`. The source module now contains no private test block, so
Mutex, Semaphore, Barrier, Condition, and RWLock are validated only through
the public candidate API. This is a test-domain boundary, not runtime lock
authority: task/queue cancellation, cross-process ownership, deadlock-cycle
reporting, and production routing remain open runtime work.

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
class ProcessPort(ABC): run_args (direct argv, ProcessOptions) → ProcessResult
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
the completion half missing from fire-and-forget `submit()`. The Rust candidate
also exposes an explicit task deadline; it does not promise preemptive closure
interruption or take ownership of WorkerPort policy.

### Rust-sink readiness (per `docs/roadmaps/frontend-kernel-roadmap.md`)

> **Boundary baseline**: `docs/roadmaps/kernel-boundary-audit.md` fixes which L1
> surfaces a Rust sink may replace (mechanism only) and which must be sealed
> first in Python — single execution authority (invoke-capability gate), a
> populated G1 whitelist, closed-by-default auth, and the B1/B2/B3 bypass paths.

The roadmap sinks hot modules to Rust **one at a time, interface unchanged,
via the port**. What is swappable vs. what a Rust sink replaces wholesale:

| Surface | Seam | Notes |
|---|---|---|
| Shell/command exec | `ProcessPort` (`get_process_port()`) | Rust uses direct argv; terminal-derived argv requires an injected `TerminalObservation`; `ProcessOptions` returns `ProcessResult` |
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

The registry-base hot path now stores descriptors in a hash index plus an
explicit order vector. Name admission and lookup are therefore expected O(1)
while overwrite keeps the original position and unregister preserves the
remaining order; public list and category views still clone in registration
order. `run_registry_base` and `rust-registry-base-bench` emit the standard v3
fixed-work evidence (`registry.base.lookup`). One local release sample with
4096 items, 1/2/4 workers, and three rounds had median derived throughput of
about 1.51M/1.52M/0.90M ops/s respectively, with zero rejections/errors; the
4-worker p99 reached roughly 77--85 us. This is candidate evidence, not a
stable uplift claim over the old vector implementation; an identical old/new
comparison is required before policy promotion.

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

Rust parity and mechanism tests for this boundary run as independent
integration targets under `crates/l1-kernel-rs/tests/<domain>/`; implementation modules
contain no inline test block. The Python infra gate
`tests/infra/test_rust_test_domain.py` enforces this public-boundary rule.

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
the Rust candidate additionally assigns FIFO writer tickets and removes timed
out tickets before waking successors. This closes queued-writer fairness for
the candidate without claiming task cancellation, cross-process ownership, or
runtime lock routing. The separate `cancellation` candidate provides a
cloneable one-way token with first-reason retention, cooperative checks, and
bounded waits. RWLock observes that token and removes cancelled writer tickets
before waking successors; queue/task cancellation remains an open mechanism
slice.

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
listeners. The Rust candidate additionally serializes callback tasks per signal
channel and scans past a busy channel, preserving same-channel FIFO while
allowing unrelated channels to progress. Blocking-callback tests cover this
Rust-native scheduling invariant; Python executor timing, overload policy,
shutdown behavior, and runtime SSE/WS fan-out remain performance and adapter
evidence.

The deterministic process parity fixture
`tests/fixtures/kernel_process_vectors.json` freezes PID/PCB registration,
READY/RUNNING transitions, identity verification, cancellation terminality,
exit-to-ZOMBIE and reap, resource totals, and timestamp-independent audit
ordering. It does not freeze the Python zombie reaper, interrupt delivery,
allocator/limiter cleanup, long-lived OS handles, or runtime process routing;
those remain adapter-owned effects. The Rust `ProcessTable` additionally
exposes a fail-closed `ProcessHandle` bridge for live PID lookup, exit, and
reap; its parity candidate uses generation one. `state_queue::ProcessHandleAllocator`
now owns a bounded reusable-slot candidate with generation-incrementing release
and stale-handle rejection, but ProcessTable storage is not switched over.

The Rust `process_adapter` candidate is the bounded one-shot implementation of
the retained `ProcessPort` value boundary. It offers direct-argument execution
and a terminal-observation path whose executable and invocation prefix are
supplied by the host probe, optional cwd/input/environment settings, per-stream
output caps with continuous draining, deadline kill, and structured
not-found/execution/timeout results. Its public tests live in the independent
`crates/l1-kernel-rs/tests/process/process_adapter.rs` target, and
`run_process_adapter`/`rust-process-adapter-bench` report the isolated
`process.adapter.oneshot` workload. A current release smoke measured roughly
707/1404/2758 ops/s at 1/2/4 workers with p95 about 1.54/1.56/1.57 ms and no
errors or rejections. This is an adapter candidate only: it does not register
children in `ProcessTable`, provide PTY or process-group semantics, reap
long-lived handles, evaluate GateChain/capability policy, or execute AgentLoop
work. Those responsibilities require a separate ownership and cutover design.

The process benchmark runner itself has no platform command fallback. Its
`ProcessBenchmarkCommand` requires a caller-injected, non-empty direct argv;
the three process benchmark binaries use their own executable plus a private
child marker as that explicit command. This keeps benchmark plumbing runnable
without selecting `/bin/sh`, `cmd.exe`, or any invocation switches inside L1.
Empty executable and empty-argument configurations fail closed in the
independent benchmark-runner test target.

The Rust `managed_process` candidate is the bounded lifecycle owner above the
one-shot value adapter. It reserves a generation-safe slot before spawning,
owns direct-argv and terminal-derived-argv children plus bounded output readers, exposes caller
stdin, distinguishes observer `Pending` from terminal completion, and requires
explicit terminate/reap. `tests/process/managed_process.rs` is the independent public
target; `run_managed_process` and `rust-managed-process-bench` report the
separate `process.managed.lifecycle` workload. A current release smoke measured
roughly 707/1391/2761 ops/s at 1/2/4 workers with p95 about 1.52/1.55/1.58 ms
and no errors or rejections. This candidate still does not provide PTYs,
process groups, capability decisions, ProcessTable registration, AgentLoop
execution, or runtime authority; those require a later ownership pilot.

The Rust `process_bridge::ProcessTableBridge` candidate now joins that managed
child lifecycle to the Rust `ProcessTable` without exposing the internal
managed handle. Spawn registers a READY row before host spawn, promotes it to
RUNNING only after spawn succeeds, and rolls back both sides on failure;
wait/terminate record ZOMBIE, and joint reap removes both the child slot and
the table row. Table-row loss is fail-closed: a managed child that has already
been reaped always releases its bridge binding, even when an external table
owner won the row-reap race. Bridge names are unique across bridge instances
sharing one table. `tests/process/process_bridge.rs` and the separate
`process.bridge.lifecycle` fixed-work benchmark cover these ownership rules;
the latest 256-item release sweep completed all work with zero errors or
rejections, and measured about 708/1401/2752 ops/s at 1/2/4 workers (p95
roughly 1.55/1.57/1.63 ms). This is still an R3 ownership candidate: PTY,
process-group termination, production reaper authority, GateChain/capability
admission, AgentLoop execution, Rust boot, and runtime cutover remain open.
The bridge also exposes a bounded `reap_finished(max_bindings)` sweep for a
future caller-owned reaper: stable raw-handle selection never exceeds the
caller budget, it never blocks on live children, reports
pending/unavailable/error counts, and consumes terminal managed slots even
when an external table transition must be reported. Zero budgets fail closed.
This is a mechanism seam only; it does not start a background thread or claim
production shutdown/reaper authority.

`ProcessTableBridge::stop_all_once` adds a matching caller-owned stop/reap
pass. It selects ProcessTable handles in stable raw order, applies the explicit
child termination timeout, jointly reaps successful bindings, and reports
pending, unavailable, error, and remaining counts. A zero budget fails before
touching any child. The pass is intentionally one-shot and does not start a
background reaper or change ProcessTable lifecycle authority.

The `process_group::ProcessGroupBook` candidate adds the next typed ownership
seam: generation-safe membership, deterministic stop plans, terminal member
outcomes, and bounded caller-driven `ProcessReaper` sweeps. It accepts only
explicit adapter observations and matching stop generations; it does not send
OS signals, create PTYs, or start a production reaper. ProcessTable runtime
authority, terminal adapters, AgentLoop execution, and shutdown ownership
remain outside this mechanism candidate.

The `process_group_runtime::ProcessGroupRuntime` candidate now composes that
group book with `ManagedProcessBook`. Direct-argv and terminal-derived-argv
children are admitted only while a group is active; failed membership admission cleans up
the spawned child before returning the capacity error. A non-blocking sweep
uses zero-deadline observation and an explicit timeout sweep may terminate a
live child, but both paths require managed-child reap and group-member reap
before reporting a terminal outcome. The independent
`tests/process/process_group_runtime.rs` target covers bounded budgets, cancellation,
admission rollback, and unknown executables. This is still a caller-owned
coordination seam: it does not create PTYs, signal an OS process group, run a
background reaper, register ProcessTable rows, or grant AgentLoop/shutdown
authority.

The group book keeps a terminal-member counter so repeated terminal
observations do not rescan the whole member map. `ProcessReaper::sweep` uses a
separate mark-and-reap fast path that avoids cloning snapshots when the caller
only needs a bounded success/error report, and selects at most the current
member budget instead of cloning every handle in a draining group. The
independent
`process.group.reaper` fixed-work runner and `rust-process-group-bench` binary
measure this member-reaping workload with a fixed 64-member sweep budget,
forcing multi-sweep bounded progress separately from process spawn, queue, and
session benchmarks; the candidate remains mechanism-only and does not grant
runtime or shutdown authority.

`ProcessGroupRuntime::drain_once` now supplies the corresponding one-shot
coordination boundary: it requests stop for every active group, performs one
caller-supplied bounded sweep, and reports requested/already-draining groups,
reaper counters, and remaining ownership. Empty groups transition directly to
`Stopped`, so a caller cannot leave an unobservable Draining group behind.
The method does not loop, sleep, start a background reaper, or choose a timeout;
the host owns repeat policy and production shutdown authority. This closes a
bounded shutdown-preparation seam only; PTY/process-group signals, terminal
rebind, and R4/R5 cutover remain open.

`ProcessGroupSignalPort` is the explicit host adapter seam for the next step.
`ProcessGroupRuntime::request_stop_with_signal` hands the adapter a stable
generation-tagged `ProcessGroupTerminationPlan` and validates the returned
`ProcessGroupSignalReport` against the exact group, generation, attempted
handle count, and delivered count. Adapter rejection or mismatch is
fail-closed and leaves ownership in `Draining` for caller policy; the Rust
candidate does not select signal numbers, create PTYs, or reap in the signal
call.

`host_process_group_signal::HostProcessGroupSignalPort` is the first concrete
closure-backed host adapter for that seam. It resolves every plan handle before
calling one host-owned sender, preserves stable plan order, rejects zero or
duplicate mappings, and bounds the sender's delivered count. The sender may
implement a platform process-group signal, a PTY control operation, or a test
double; no signal number, PID lookup, terminal scan, or retry policy is stored
in L1. Resolver failure prevents sender dispatch, so a missing host mapping
cannot produce a partial batch.

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

### Terminal probe and Agent process admission

The Rust `terminal_probe` candidate closes the host-terminal discovery value
boundary without making the kernel a host scanner. A host adapter injects
validated observations containing terminal family, resolved executable,
invocation prefix, version, availability, interactive/PTY support, encoding,
and probe source. `TerminalProbe` applies only caller-supplied requirements,
allow-lists, and preference order; it has no PATH lookup, environment fallback,
or built-in shell path. `TerminalObservation::command_argv` lets an adapter
construct an exact shell argv for CMD, PowerShell 7, Bash, Git Bash, or a
host-defined terminal while keeping the executable and switches outside L1.
`PlatformDescriptor` retains host metadata only and does not construct shell
argv, so platform helpers cannot bypass the probe boundary.
The independent `tests/terminal/terminal_probe.rs` target covers deterministic
selection, custom invocation construction, duplicate identity rejection, and
no-eligible fail-closed behavior.

The Rust `process_constraints` candidate is the hard Agent-process admission
seam above managed children. It validates Agent/Cell identity, security ring,
direct versus shell mode, discovered terminal identity/family/invocation,
working-directory prefixes, environment-key policy, timeout, output/CPU/memory
ceilings, and process-group membership. `ProcessGroupRuntime::spawn_constrained`
must evaluate this receipt before spawning, reject adapter executable/cwd/env
overrides that diverge from the admitted request, and does not discover a
terminal on behalf of the caller. Shell argv must contain a command after the
injected invocation prefix. The independent `tests/process/process_constraints.rs`
target covers successful shell/direct admissions, accumulated policy
violations, and pre-spawn override rejection. The companion
`spawn_gated_constrained` entry requires the explicit `process.spawn`
capability and matching gate/process identity before evaluating the GateChain
receipt and delegating to the same constraint path; GateChain denials are
audited by its ledger, while correlation mismatches fail closed before the
ledger and never create a child.
The low-level `spawn_args` methods remain mechanism helpers, while the removed
implicit-shell entry points are not part of the Rust contract. This slice does
not yet grant ProcessTable, AgentLoop, PTY, shutdown, or production runtime
authority.

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
