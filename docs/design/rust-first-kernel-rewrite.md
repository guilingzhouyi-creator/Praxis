# Rust-First Kernel Rewrite Decision

> Status: approved architecture direction; implementation remains isolated in
> the Rust build workspace until the rewrite checkpoints are complete.

## 1. Decision

The future Praxis kernel is a **clean-break Rust build**, not a Python
drop-in replacement and not a user-data migration project. There are no
production users whose persisted Python state must be read by the new kernel.
The rewrite may choose new state directories, schemas, scheduling algorithms,
allocation strategies, error taxonomy, and internal APIs.

The current Python kernel is still useful as an architectural reference. It is
not the authority for Rust implementation details and its quirks are not
automatically requirements. Rust becomes the authority only in the separate
rewrite build after the security, performance, and cutover gates in this
document are met.

## 2. What Shared Vectors Mean

Shared vectors are **not user-data compatibility fixtures**. They answer a
narrower question: after mapping the existing architecture into a new design,
did the new kernel preserve the invariants that must remain true?

| Vector class | Rust requirement | Examples |
|---|---|---|
| Security invariants | Must match | fail-closed authorization, terminal cancellation, audit causality |
| Observable control semantics | Match unless explicitly redesigned | lifecycle terminal states, bounded history, resource totals |
| Wire boundaries | Match only for a retained protocol; otherwise version a new boundary | TS bridge records, health/evidence records |
| Python behavior | Reference only | dict ordering, exception text, reaper timing, singleton layout |
| Performance workload | Must be reproducible, not byte-compatible | fixed work, queue pressure, lock contention, tail latency |

The existing `tests/fixtures/kernel_*_vectors.json` files therefore serve as
executable semantic baselines. A Rust redesign may reject a vector only after
recording the intentional semantic change, its security impact, and the new
Rust-native invariant. Passing a vector never authorizes FFI, boot wiring, or
runtime replacement.

## 3. Rust-Native Performance Shape

The rewrite is optimized around ownership and data movement, not around
mechanically reproducing Python classes:

1. Keep hot-path values typed and compact. Serialize to JSON or another wire
   format only at process/IPC/TS edges; do not put `serde_json::Value` in inner
   scheduling or accounting loops.
2. Use generational process handles and sharded tables so unrelated process
   operations do not contend on one global lock. Handle reuse must fail closed
   after generation rollover.
3. Use bounded per-core queues with explicit backpressure. Queue depth,
   rejection, wait time, and fairness are first-class counters rather than
   private executor state. The current queue keeps fail-fast admission as the
   default and drains consumer batches under one lock. Blocking
   condition-variable admission remains an explicitly measured alternative,
   not an assumed optimization.
4. Keep policy evaluation pure and snapshot-driven. Providers, filesystem,
   model calls, prompts, DVG, R5/Mer, and AgentLoop orchestration/execution stay outside
   the kernel hot path.
5. Make audit ordering explicit. Security decisions publish a sequence before
   acknowledgement; non-critical telemetry may batch or drop under a declared
   overload policy.
6. Measure before selecting lock-free, actor, async-runtime, or custom
   allocator techniques. A more complex primitive is not a performance win
   without fixed-work evidence on the target platform.

## 4. Rewrite Gates

| Gate | Deliverable | Exit condition |
|---|---|---|
| R0 semantic map | Map Python modules to Rust responsibilities and mark preserved/redesigned/removed semantics | Every removed Python behavior has an owner or explicit non-goal |
| R1 native skeleton | Rust workspace with typed IDs, state ownership, bounded queues, wire adapters, and counters | `cargo test`, fmt, Clippy, and stress smoke are reproducible |
| R2 performance baseline | Rust fixed-work benchmark plus Python reference measurements | Throughput, p95/p99, CPU, memory, queue/lock waits, and drop counts are recorded |
| R3 mechanism closure | Process, event, allocator, capability, audit, persistence, and IPC mechanisms | Security vectors and Rust-native invariants are green; intentional divergences are documented |
| R4 kernel assembly | Rust-owned boot/config/state layout and versioned protocol boundary | No Python import or FFI is required by the new kernel |
| R5 clean cutover | New build entrypoint, fresh state initialization, recovery/rollback procedure | Cutover can start empty and recover from Rust-owned state without Python runtime authority |

The current preflight branch has advanced through the R1 substrate and most R3
mechanism candidates into R4 assembly/runtime preparation. Its parity and
fixed-work tests are still evidence for semantic and performance decisions, not
evidence that the final Rust kernel has production boot, AgentLoop, provider, or
cutover authority. R5 clean cutover remains pending.

## 5. Immediate Work

The first R1 implementation slice is now present in
`crates/l1-kernel-rs/src/substrate.rs`: typed generation-tagged process
handles, deterministic shard planning, and allocation-free atomic queue
metrics. The fixed-work benchmark schema is now present in
`crates/l1-kernel-rs/src/benchmark.rs`. The first Rust-owned state/queue
prototype is now present in `crates/l1-kernel-rs/src/state_queue.rs`, and
`crates/l1-kernel-rs/src/benchmark_runner.rs` provides a bounded-queue
contention smoke that emits complete worker/round coverage with p95/p99,
queue/lock waits, and rejection counts. The queue also exposes a token-aware
wait that returns `Cancelled` before claiming work. It must remain a build-only candidate
until R2 evidence exists. The `reputation` candidate now supplies a policy-
injected G5 score ledger without singleton, persistence, or provider authority.
The `notify` candidate now supplies a bounded side-channel buffer without
EventBus or transport authority. The repeatable report export slice now
includes a v3 resource contract: CPU nanoseconds, RSS bytes, queue/lock waits,
p95/p99, rejection counts, and explicit source/unavailable markers.
`BenchmarkEvidence` validates the units and sample availability, while
`scripts/py/r2_baseline_bundle.py` runs the independent Python reference under
the same fixed-work specification and stores both reports in one comparison
artifact. This closes the measurement scaffolding portion of R2 but does not
make a performance cutover decision or grant runtime authority.

The benchmark runner also exposes a separate WorkerPool batch workload and the
`rust-worker-bench` binary. It validates fixed work with queue capacity covering
the entire batch and reports submission-tail plus batch-throughput evidence;
these samples are intentionally not merged into the cross-language queue
contention bundle. The first local release run completed every 4096-item sample
with zero errors/rejections but showed lower throughput at 2 and 4 workers for
trivial closures, leaving task handoff/queue design as the next optimization
target.

The session truth candidate now uses hash indexes for message-id duplicate
checks and sharded session admission; deterministic ordering is retained only
at the snapshot boundary. `run_session_book` and `rust-session-bench` measure a
separate fixed-total `session.book.admission` workload (create, activate, and
input) with the v3 throughput, p95/p99, CPU/RSS, and rejection/error fields.
Because this workload has no queue boundary, queue/lock waits are explicitly
zero and must not be compared with WorkerPool or substrate queue contention
waits. A release smoke completed 4096 items for every 1/2/4-worker sample with
zero errors/rejections; this is a candidate hot-path result, not a cutover
decision.

`SessionBook::create_batch` now provides an explicitly separate grouped
admission candidate. It validates each spec before touching registry state,
groups successful specs by shard, acquires each shard lock once, and preserves
input order with per-item failure results. `run_session_book_batch` and
`rust-session-batch-bench` use the same fixed-work schema but report batch
latency independently from per-session admission; the two distributions must
not be compared as though they had the same operation unit.
One release smoke measured median batch throughput of about 1.67M/1.78M/2.64M
ops/s at 1/2/4 workers with zero errors/rejections; median batch p99 was about
61/133/203 us. These are candidate comparison samples, not a default scaling
policy or a clean-cutover proof.

The terminal mailbox candidate now has the same evidence split. `TerminalBook`
uses hash lookup internally and deterministic sorting only for snapshots, while
normal mailbox operations use a read-locked registry plus per-terminal record
locks, and batch submit/drain methods acquire one record lock per batch while
retaining FIFO, sequence, capacity, drop-counter, and per-frame error behavior. The separate
`terminal.book.mailbox` and `terminal.book.batch_mailbox` runners and release
bins measure per-frame versus per-batch latency under the v3 fixed-work schema;
The latest Linux x86_64 release smoke for the record-lock variant reported
median throughput of approximately 4.63M/6.00M/6.08M ops/s for the per-frame
path and 7.53M/12.14M/11.65M ops/s for the 32-frame grouped path at 1/2/4
workers, with zero errors/rejections. Four-worker grouped p99 was 5.6 us at
the median round (36.5 us worst round); cross-run comparisons remain evidence
only because the runner is not a pinned benchmark host. PTY/subprocess
ownership and AgentLoop routing remain outside this candidate.

The worker candidate connects `TaskHandle` to the cancellation token and adds
`submit_result_with_timeout`: queued work can finish with a structured
`Cancelled` or `TaskTimeout` result before its closure starts, while an
already-running closure is not forcibly interrupted. A closure that completes
after its deadline is reported as `TaskTimeout`; the caller's wait deadline is
the distinct `Timeout` result. WorkerPort ownership, adaptive sampling, and
Python exception mapping remain adapter decisions. Worker snapshots expose
cancelled, timed-out, and failed execution outcome counters, and update those
counters before releasing the result handle so completion observation and
accounting are ordered. The worker hot path now stores pool-size, active,
completion, rejection, and outcome gauges in atomics; only the bounded queue
and worker join list retain mutex ownership. The public worker integration
target covers concurrent submission and checks completed plus evicted work
against the fixed submission count, while the change remains an evidence-backed
candidate rather than an automatic runtime policy decision.
The final active-counter transition is also the drain notification point, so
the worker no longer reacquires the queue mutex after every completed task just
to inspect emptiness; shutdown still checks queue depth and active workers
before joining. Workers now claim at most eight FIFO tasks under one queue lock
and reuse a bounded local buffer. The active count covers
claimed-but-not-yet-completed tasks, preserving shutdown timeout semantics while
work is held locally. This reduces handoff locking for the fixed closure
workload, but the release evidence still shows lower two/four-worker
throughput; no scaling policy is promoted from this candidate.
The WorkerPool evidence path now records aggregate batch-claim wait in the
standard `queue_wait_ns` field. A current 4096-item release sweep measured
median waits of approximately 1.0 ms, 19.7 ms, and 177.8 ms for 1/2/4 workers,
respectively, alongside lower multi-worker throughput. This quantifies the
handoff bottleneck and keeps future queue designs accountable to the same
fixed-work schema.
The grouped `WorkerPool::submit_result_batch` path now wakes only the smaller
of the submitted batch and resident worker count with repeated `notify_one`
calls, avoiding an unconditional condition-variable broadcast. FIFO claims,
oldest-pending eviction, task completion, and shutdown behavior remain
unchanged. This is still an evidence-backed candidate: the same v3 fixed-work
matrix must show a repeatable throughput/tail win before runtime promotion.
The Rust `agent_loop` candidate now provides the logical routing seam between
SessionBook truth and TerminalBook correlation. It validates
agent/cell/session/terminal identity, models loop lifecycle, and holds loop
state across each Session admission so stop and input/event writes are
linearizable. It intentionally does not execute AgentLoop provider/model/tool
work, prompt policy, PTY/subprocess I/O, terminal mailbox mutation, or WorkerPool
tasks; those remain adapter-owned. The independent `tests/agent_loop.rs` target
covers correlation failures, lifecycle transitions, sequence receipts, and
failed admission accounting. `run_agent_loop`/`rust-agent-loop-bench` measure
the same fixed-work input path with loop mutex waits; with the contention-only
probe, the current 4096-item release smoke has median throughput about
1.819M/0.761M/0.760M ops/s and contended waits 0/5.011/13.583 ms for 1/2/4
workers. The initial shared routing mutex exposed multi-worker contention, so
the next candidate replaces it with a lifecycle `RwLock` plus atomic command
and admission counters. Admissions hold a read lock across the authoritative
Session write; pause/stop take the write lock and therefore wait for in-flight
admissions before closing the loop. This keeps `input_seq` in Session, retains
fail-closed lifecycle transitions, and permits concurrent same-loop admissions.
The independent concurrency test verifies unique contiguous command and input
sequences. A local fixed-work release sample reached about 2.49M/2.18M/0.90M
ops/s at 1/2/4 workers with zero errors/rejections; this is evidence for the
candidate hot path only and does not promote runtime authority.
The lock-wait probe was then made contention-only: an uncontended `try_lock`
does not read the clock or update the atomic counter, while a blocked fallback
records elapsed wait. This reduces measurement overhead on the serialized
admission hot path; the field remains a wait metric, not total lock-hold time.
The next grouped-admission slice adds `Session::append_input_batch` and
`AgentLoopHandle::admit_input_batch`. The session validates and appends each
item under one session lock with partial-success semantics; the loop holds its
lifecycle read lock once, maps successful items to contiguous command receipts, and
counts failed items without advancing the command sequence. The dedicated
`agent.loop.batch_admission` runner and `rust-agent-loop-batch-bench` binary
report per-batch p95/p99 and loop lock wait under the same v3 fixed-work
contract. Batch and per-input latency units remain separate, and the slice
does not execute providers/tools or promote Rust runtime authority.

The next process-boundary slice is now present as the Rust
`process_adapter::ProcessAdapter` candidate. It implements only bounded
one-shot `ProcessPort` behavior: direct argument execution, an explicit shell
path, optional cwd/input/environment/executable values, separately drained and
retained stdout/stderr, deadline kill, and structured adapter errors. The
independent `tests/process_adapter.rs` target and the
`process.adapter.oneshot` fixed-work runner cover the value boundary and
release evidence. The latest release smoke measured about 707/1404/2758 ops/s
at 1/2/4 workers, p95 about 1.54/1.56/1.57 ms, and zero errors/rejections.
This does not close R3 or R4: no child is registered in ProcessTable, no
long-lived handle or PTY is owned, and no GateChain, capability, AgentLoop, or
runtime execution path is wired. The next process work must first define
ownership/reaping and cancellation semantics before any production adapter
pilot.

The process lifecycle slice now adds `managed_process::ManagedProcessBook`.
It reserves generation-safe child slots before spawn, owns bounded output
drainers and explicit stdin, separates observer timeout (`Pending`) from
termination, and releases a slot only after terminal `reap`. The independent
`tests/managed_process.rs` target and `process.managed.lifecycle` fixed-work
runner provide the first ownership/reaping evidence; current release medians
are about 707/1391/2761 ops/s at 1/2/4 workers with p95 about 1.52/1.55/1.58
ms and zero errors/rejections. PTY, process-group, capability, ProcessTable,
AgentLoop, and runtime wiring remain deliberately out of scope. The one-shot
stdin-pipe fast path was measured against its prior baseline but did not show
a stable cross-worker win, so it is retained as a local implementation detail
without policy promotion.

The next process slice is `process_bridge::ProcessTableBridge`. It makes the
ProcessTable handle the only public identity while keeping the managed child
book private. The bridge registers a READY PCB before spawn, transitions to
RUNNING after successful host spawn, rolls back registration on spawn failure,
records terminal exits as ZOMBIE, and jointly reaps the child and PCB. If an
external owner removes the PCB first, the bridge returns a structured reap
error but still drops the already-consumed binding; bridge registration names
are unique when multiple bridge instances share one table. The independent
`tests/process_bridge.rs` target and `process.bridge.lifecycle` fixed-work
runner now provide this ownership evidence. A 256-item Linux x86_64 release
sweep completed with zero errors/rejections and about 708/1401/2752 ops/s at
1/2/4 workers (p95 about 1.55/1.57/1.63 ms). This closes only the candidate
ownership seam. PTY, process groups, a production reaper, GateChain/capability
admission, AgentLoop execution, boot ownership, and R4/R5 cutover remain
required before any process adapter pilot.

The bridge now also provides a bounded `reap_finished` sweep for a future
caller-owned reaper. It snapshots handles, observes with a zero deadline, and
never blocks on live children. A table transition conflict still consumes the
terminal managed slot before returning an error count, so the sweep cannot
leave an unrepeatable binding behind. No background thread, shutdown hook, or
production reaper authority is introduced by this candidate.

The next process-group candidate is `process_group::ProcessGroupBook` with
`ProcessReaper`. It owns generation-safe membership, deterministic stop-plan
ordering, terminal outcome accounting, and explicit bounded sweep budgets.
Reaper observation is caller supplied and can only produce pending,
unavailable, or terminal outcomes; terminal members are reaped only after the
group authority accepts the matching stop generation. This closes the typed
process-group and caller-owned reaper mechanism seam without sending OS
signals, creating PTYs, starting a background thread, or granting shutdown
authority. PTY/session adapters, ProcessTableBridge wiring, GateChain and
capability admission, AgentLoop execution, and R4/R5 cutover remain outside
this candidate.

`scripts/py/r2_baseline_analyze.py` now summarizes that artifact by worker and
language, including scaling efficiency, p95/p99 medians, rejection/error
ratios, queue/lock wait summaries, and available resource medians. Its output
is descriptive evidence only; thresholds and cutover decisions remain an
explicit future review. The
first R3 mechanism closure slice is the Rust-native `identity_binding`
metadata registry: it freezes the write gate, binding cap,
stable identity ID, revision, and snapshot invariants while explicitly leaving
prompt content, persistence, events, and API routing in adapters. No Python
FFI, boot integration, Port replacement, or production state migration is part
of this work. Its shared vector intentionally covers only authorization and
mutation lifecycle, not prompt bytes, random UID bodies, or Python persistence.
The following R3 mechanism slice is the transport-neutral `network::PeerBook`:
clock injection, endpoint validation, timeout/loss/eviction state, and
deterministic snapshots are frozen, while socket/TLS/discovery and EventBus
delivery remain adapters.

The process parity candidate now exposes an explicit typed-handle bridge:
live PIDs in the substrate slot range map to generation-one `ProcessHandle`
values, stale generations fail closed, and handle-based exit/reap stop working
after removal. This is an adapter seam only; reusable slot generations remain
owned by the Rust-native sharded state store until ProcessTable storage is
rewritten. `state_queue::ProcessHandleAllocator` now provides that bounded
candidate: released slots increment their generation, duplicate or stale
releases fail closed, and capacity exhaustion is explicit. It is not yet wired
into ProcessTable or runtime scheduling.

The next assembly-preparation slice is the declarative `boot::BootPlan`. It
owns only validated step metadata, explicit replacement, a pre-execution lock,
and dependency-first ordering. Missing dependencies, invalid names, duplicate
registrations, and cycles fail closed. The shared
`kernel_boot_plan_vectors.json` fixture is consumed by Rust and Python tests;
Python's historical omission of missing dependencies is recorded as an
intentional reference difference. This slice does not execute callbacks, read
configuration, start workers, mutate lifecycle state, or provide boot
authority. R4 still requires a separate Rust-owned config/state layout and
versioned protocol boundary.

The first concrete R4 state slice is `state_layout::StateLayoutManifest`.
It defines a new Rust-owned root with a versioned manifest, canonical relative
entries, parent-directory coverage, and explicit fresh-state paths. A
`StateProbe` supplied by the host is reduced to `initialize`, `resume`,
`recover`, `migrate`, or fail-closed `reject`. The candidate performs no
filesystem I/O, imports no Python state, and runs no migration callback; those
effects remain behind the future R4 adapter boundary.

The next R4 slice is now present in `state_store::StateStore`. It is a
filesystem-bearing adapter for a new Rust root only: it validates the manifest,
creates declared directories/files, and atomically persists lifecycle and
runtime checkpoint records. Clean roots resume; unclean roots require an
explicit recovery transition. Divergent or migration-required roots fail
closed. No Python state, FFI, or Python boot authority crosses this seam.

The mechanism port boundary is now represented by `ports::PortRegistry` and
its value types. This preserves only deterministic descriptor registration and
the primitive `Result`/endpoint/message/input-activity shapes needed by future
adapters. Registration is explicitly locked before wiring; duplicate or
invalid descriptors fail closed. No Rust candidate in this slice opens files,
sockets, subprocesses, threads, or hardware monitors.

`assembly::KernelAssembly` now provides the first executable R4 seam by
composing the declarative boot, state-layout, config-manifest, protocol,
terminal-contract, port, and lifecycle candidates.
The standalone `rust-kernel` binary emits a deterministic JSON snapshot and
has no Python or FFI dependency. The assembly remains a build-only proof;
`state_store` now covers fresh-root creation and durable recovery, while
the `protocol` candidate now validates the retained v1/TS-neutral wire values,
canonical JSON, and bounded replay cursor. HTTP/WS serving, provider wiring,
clock ownership, and runtime session state remain adapter obligations. The
`config_store` candidate now supplies the independent JSON manifest/config/
settings root with atomic document updates; Python YAML/settings migration and
engineering-debug policy remain explicitly out of scope.

The `execution_store` adapter is the next R4/R5 recovery slice. It writes one
versioned, atomically replaced document for the Rust-owned `SessionBook`,
`TerminalBook`, and `AgentLoopBook`, with deterministic ordering and explicit
cross-book identity checks. A clean checkpoint refuses writable sessions,
active loops/terminals, queued terminal frames, or any live process binding.
An unclean checkpoint discards non-persisted terminal queues and process ids,
marks writable sessions crashed, marks active loops failed, and returns active
terminals as unbound `Created` records. Restore is therefore explicit and
fail-closed; no PID/PTY is fabricated and no Python state or runtime authority
crosses this boundary. The independent `tests/execution_store.rs` target
covers clean round-trip, unclean recovery, rejection, and version failure.

The Rust `terminal` candidate is the first lower-layer substrate reserved for
upper-layer AgentLoop terminals. It owns unique terminal/session/process
bindings with typed generation-tagged `ProcessHandle` storage, while the
retained raw process id is emitted only at the snapshot wire boundary. It also
owns explicit lifecycle terminality and bounded opaque input/output mailboxes.
PTY/process adapters, AgentLoop orchestration, prompts, tools, rendering, and
frontend multiplexing remain outside the clean-break kernel. Terminal
contract/version mismatches are rejected during assembly rather than being
silently downgraded.

The R4 protocol entry preparation now includes `protocol_host::ProtocolHost`.
It bounds one JSONL frame before decoding, validates the retained v1 envelope,
and emits recursively canonical JSON for accepted input. The standalone
`rust-protocol-gate` binary is intentionally a validation/canonicalization
smoke only: rejected lines are diagnostics, and no command, intent, session,
AgentLoop, or provider work is executed. This keeps the future TS bridge on a
versioned Rust boundary without prematurely granting runtime authority.

The `scheduler::KernelScheduler` candidate is the first explicit execution
ownership seam: it composes generation-safe slots, sharded lifecycle state, and
bounded typed work. It validates queue admission rollback, stale work discard,
and stop/reap transitions, but intentionally starts no threads and does not
claim boot, AgentLoop, or provider authority.

The `runtime::KernelRuntime` candidate is the first explicit Rust execution
host. It composes locked assembly metadata, the lifecycle FSM,
`KernelScheduler` state ownership, and WorkerPool submission into a bounded
boot/submit/cancel/reap/shutdown surface. Task deadlines remain distinct from
observer wait timeouts, and shutdown drains accepted work before entering
`halted`. This is still a candidate-only host: Python state, PTY/subprocess,
AgentLoop routing, provider wiring, prompt/tool policy, and production
cutover/recovery authority remain outside the module. The persistent
constructor attaches `StateStore` to the same lifecycle, writes a fresh Rust
root, and turns unclean reopen into an explicit recovery transition without
importing Python state. Capability-shaped work uses `submit_gated`, which
requires matching caller/tool identities, evaluates G1-G5, and remains
fail-closed when the whitelist or executor is absent.

The queue optimization slice keeps `try` admission as the default and adds a
bounded consumer drain to reduce lock acquisitions. Each drained batch now
records completion with one atomic counter update plus a saturating depth CAS;
fixed-work completion and duplicate-completion underflow behavior are unchanged.
An additional producer claim-batch experiment was measured against the same
fixed-work matrix and rejected: although 1-2 worker samples sometimes improved,
4-worker median tail latency regressed, so per-item admission remains the
benchmark reference until a cross-worker win is demonstrated.
The consumer batch-size sweep was repeated three times per setting on the same
4096-item, 1/2/4-worker, three-round workload: batch 64 reduced median
throughput versus the default batch 32 at all worker points (about 9.1%, 1.6%,
and 3.6%) and raised p95 latency. The occasional 4-worker p99 improvement was
not sufficient to offset those regressions, so batch 32 remains the fixed
reference.
`blocking` admission is available through `PRAXIS_RUST_QUEUE_MODE=blocking` and
`make rust-benchmark-blocking` only as a comparison path. On the current host
it eliminates rejects but creates multi-worker condition-variable convoy and
higher p95 latency, so it is not promoted to runtime authority.

The mechanism tests for `state_queue`, `process`, `terminal`, `session`, `agent_loop`, `substrate`,
`benchmark`, `health`, `territory`, `registry`, `identity_uid`, `swapper`,
`tool_chain`, `schema`, `migration`, `capability`, `cancellation`, `notify`,
`reputation`, `audit`, `device`, `interrupt`, `errors`, `benchmark_runner`,
`channel`, `bus`, `registry_base`, `event`, `scheduler`, `runtime`, `worker`, `network`,
`rule_descriptor`, `boot`, `ports`, `identity_binding`, `state_layout`,
`state_store`, `config_store`, `platform`, `paths`, `discovery`, `lifecycle`,
`assembly`, `contract`, `ipc`, `persist`, `protocol`, `constitution`,
`gatechain`, `allocator`, `vfs`, `load_adaptive`, and `versioning` now live
under `crates/l1-kernel-rs/tests/` as independent Rust test targets. The crate
contract-version check is part of `contract_vectors.rs`; no inline test module
remains in `lib.rs`. The worker scaling test uses only public submission and
shutdown behavior, so the clean-break public boundary remains explicit for
later TS and Rust runtime rebuilds.

The `sync` mechanism follows the same split: `tests/sync.rs` contains the
eleven public Mutex/Semaphore/Barrier/Condition/RWLock behavior tests, while
`tests/sync_vectors.rs` keeps the cross-language RWLock vectors. No private
sync test module remains in the implementation, and this migration does not
promote synchronization to runtime authority.

The channel mechanism slice now consumes shared FIFO/overload/overwrite/close
vectors on both sides. Rust keeps the channel as a JSON edge primitive rather
than an inner scheduler value, and draining wakes all blocked producers after
capacity is released. Socket, IPC transport, and AgentLoop routing remain
adapter responsibilities.

The Constitution mechanism slice now validates custom rule snapshots before
replacement: IDs and sources are constrained, custom rules are data-only
`noop` descriptors, tags are sorted/deduplicated, and duplicate or malformed
rules fail closed without mutating the previous snapshot. Markdown loading,
posture providers, and runtime policy routing remain adapter-owned.

The EventBus candidate now uses signal type as a dispatch channel: at most one
callback task for a channel runs at a time, while workers scan past busy
channels to preserve cross-channel progress. This gives same-channel FIFO
without a global slow-callback barrier. The behavior is a Rust-native
mechanism invariant covered by blocking-callback tests; Python executor timing
and SSE/WS fan-out remain outside the rewrite boundary.

The synchronization candidate now assigns monotonically increasing tickets to
queued writers. A writer can acquire only when its ticket reaches the head;
timeout removal advances the queue and wakes successors. This closes writer
fairness independently of Python's condition-variable timing while preserving
the retained RWLock value vectors. The separate cancellation candidate adds a
cloneable one-way token, first-reason retention, cooperative checks, and
bounded waits; RWLock removes a cancelled writer ticket before waking
successors. Task/queue cancellation, cross-process lock ownership, and runtime
routing remain later mechanism work.
