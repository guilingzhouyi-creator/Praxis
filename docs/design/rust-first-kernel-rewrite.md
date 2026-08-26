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
tasks; those remain adapter-owned. The independent `tests/session/agent_loop.rs` target
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

The `agent_loop_execution::AgentLoopExecutionBridge` now provides a bounded
execution seam above that routing state. A caller submits an input and an
`AgentLoopAction`; the runtime worker admits the input only after task
admission, passes the authoritative receipt and loop identity to the action,
and can admit one returned event. Versioned reports and failures retain the
input/event receipts, failure stage, and any partial input admission. A
pre-execution cancellation therefore leaves Session unchanged, while action
panic is converted to a structured failure. This joins Rust AgentLoop,
WorkerPool, and Session mechanisms without discovering provider/prompt/tool/
PTY behavior, rolling back side effects, or granting production authority.
The independent target is `tests/runtime/agent_loop_execution.rs`.

The next process-boundary slice is now present as the Rust
`process_adapter::ProcessAdapter` candidate. It implements only bounded
one-shot `ProcessPort` behavior: direct argv execution, or terminal-derived argv
from an injected `TerminalObservation`, optional cwd/input/environment values,
separately drained and retained stdout/stderr, deadline kill, and structured adapter errors. The
independent `tests/process/process_adapter.rs` target and the
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
`tests/process/managed_process.rs` target and `process.managed.lifecycle` fixed-work
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
`tests/process/process_bridge.rs` target and `process.bridge.lifecycle` fixed-work
runner now provide this ownership evidence. A 256-item Linux x86_64 release
sweep completed with zero errors/rejections and about 708/1401/2752 ops/s at
1/2/4 workers (p95 about 1.55/1.57/1.63 ms). This closes only the candidate
ownership seam. PTY, process groups, a production reaper, GateChain/capability
admission, AgentLoop execution, boot ownership, and R4/R5 cutover remain
required before any process adapter pilot.

The bridge now also provides a bounded `reap_finished(max_bindings)` sweep for
a future caller-owned reaper. It selects stable raw handles up to the caller
budget, observes with a zero deadline, and never blocks on live children. A
table transition conflict still consumes the terminal managed slot before
returning an error count, so the sweep cannot leave an unrepeatable binding
behind; zero budgets fail closed. No background thread, shutdown hook, or
production reaper authority is introduced by this candidate.

The bridge stop-preparation follow-on adds `ProcessTableBridge::stop_all_once`.
It selects a stable raw-handle prefix, applies the caller timeout to each
selected child, jointly reaps successful ProcessTable/managed bindings, and
returns explicit terminated, pending, unavailable, error, and remaining
counts. It performs one bounded pass only; a zero budget is rejected before
child access, and callers retain repeat policy plus production shutdown
authority.

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

The follow-on `process_group_runtime::ProcessGroupRuntime` candidate composes
the typed group book with `ManagedProcessBook` at the Rust boundary. It admits
direct-argv or terminal-derived-argv children only into active groups, rolls back a child when group
capacity rejects membership, and exposes both zero-deadline and explicit
timeout reaper sweeps. A terminal result is published only after the managed
child slot and the group membership have both been reaped. The independent
runtime test target covers fixed member budgets, cancellation, rollback, and
not-found execution. This remains an adapter seam, not production process
supervision: PTY, OS process-group signaling, ProcessTable registration,
AgentLoop execution, background reaping, and R4/R5 cutover remain open.

The shutdown-preparation follow-on adds `ProcessGroupRuntime::drain_once`.
It requests stop for all active groups, performs one bounded caller-supplied
sweep, and returns deterministic reaper counters plus remaining group/member
ownership. Empty groups enter `Stopped` when the stop request is accepted,
preventing a zero-member group from staying in `Draining` forever. The API does
not loop, start a background thread, choose a timeout, or claim production
shutdown authority; hosts repeat it under their own lifecycle policy.

The next host boundary adds `ProcessGroupSignalPort` and
`request_stop_with_signal`. Rust emits a stable generation-tagged termination
plan; the host chooses its platform signal or PTY operation and returns a
`ProcessGroupSignalReport`. The report must echo group/generation and bounded
attempted/delivered counts before the caller proceeds to a separate reaper
sweep. Adapter failure or mismatch leaves the group draining and fails closed;
Rust never hardcodes signal numbers, discovers terminals, or owns retry and
shutdown policy.

The first adapter implementation is
`host_process_group_signal::HostProcessGroupSignalPort`. It accepts explicit
resolver and sender closures, resolves the complete handle batch before any
host operation, and validates non-zero unique targets plus bounded delivery.
This is a host-injection seam rather than a platform implementation: Linux,
Windows, PTY, permission, and retry behavior remain outside the Rust crate.

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

The boot execution follow-on adds `BootPlan::execute` after the plan lock. The
caller supplies one `BootAction` per declared step; the executor validates the
set before any callback, runs dependency-first, and converts callback errors or
panics into structured failures carrying the completed prefix. It does not
discover provider handlers, roll back side effects, advance lifecycle, or make
the Rust plan the production boot authority.

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

The T4a `input_activity` candidate is the first cross-language projection above
that port. `InputActivityProbe` and the TypeScript reducer consume only bounded
host-injected source labels, permission states, aggregate keyboard/pointer
flags, and caller time. Both implementations apply the same positive idle
window and source-count limit, reject duplicate or whitespace-bearing labels,
future/non-finite timestamps, and activity asserted without granted permission,
then emit the existing `InputActivitySnapshot`. The shared
`kernel_input_activity_vectors.json` fixture covers the Rust integration target
and TypeScript tests. No device node, raw key value, pointer coordinate, or
system clock enters either implementation. T4b is intentionally separate: it
must provide platform adapters, permission UX, and privacy/failure evidence
before any production wiring review.

`assembly::KernelAssembly` now provides the first executable R4 seam by
composing the declarative boot, state-layout, config-manifest, protocol,
terminal-contract, port, and lifecycle candidates.
The standalone `rust-kernel` binary requires an explicit state-root argument
and emits a deterministic JSON snapshot with no Python or FFI dependency. The
assembly remains a build-only proof;
`state_store` now covers fresh-root creation and durable recovery, while
the `protocol` candidate now validates the retained v1/TS-neutral wire values,
canonical JSON, and bounded replay cursor. HTTP/WS serving, provider wiring,
clock ownership, and runtime session state remain adapter obligations. The
`config_store` candidate now supplies the independent JSON manifest/config/
settings root with atomic document updates; Python YAML/settings migration and
engineering-debug policy remain explicitly out of scope.

The `preflight` candidate is the next R4 entry preparation slice. It accepts
only a caller-supplied `AssemblySpec` and `StateProbe`, validates both through
the existing assembly boundary, and emits a versioned report containing the
deterministic assembly snapshot, state action, and operator disposition.
`rust-kernel-preflight` is a JSON stdin/stdout tool exposed through
`make rust-kernel-preflight`; it performs no host probing, filesystem mutation,
boot execution, process rebind, or Python fallback. This closes the read-only
entry evidence seam but does not close R4 boot ownership or the R5 clean
cutover/recovery procedure.

The follow-on `entry` candidate makes the Rust-owned entry lifecycle explicit
without promoting it to production authority. `EntryRequest` requires a
versioned assembly, JSON-safe runtime limits, and an explicit `inspect` or
`boot_once` operation. The coordinator opens only the fresh Rust state root,
surfaces the current recovery decision, and refuses an unclean boot until the
caller supplies the exact same generation/action/reason acknowledgement. A
`boot_once` run captures the active runtime snapshot and then performs bounded
clean shutdown before returning, so the one-shot binary cannot report success
while leaving a live runtime behind. Invalid configuration, stale
acknowledgements, and rejected roots fail closed. `rust-kernel-entry` is a
bounded stdin/stdout smoke harness; it does not select defaults, probe shells,
execute providers/AgentLoop work, rebind processes, or close R5 cutover.

The `execution_store` adapter is the next R4/R5 recovery slice. It writes one
versioned, atomically replaced document for the Rust-owned `SessionBook`,
`TerminalBook`, and `AgentLoopBook`, with deterministic ordering and explicit
cross-book identity checks. A clean checkpoint refuses writable sessions,
active loops/terminals, queued terminal frames, or any live process binding.
An unclean checkpoint discards non-persisted terminal queues and process ids,
marks writable sessions crashed, marks active loops failed, and returns active
terminals as unbound `Created` records. Restore is therefore explicit and
fail-closed; no PID/PTY is fabricated and no Python state or runtime authority
crosses this boundary. The independent `tests/session/execution_store.rs` target
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

The runtime now owns the three Rust execution metadata books needed by the
independent entry boundary: `SessionBook`, `TerminalBook`, and
`AgentLoopBook`. `open_persistent` restores them from the separate
`ExecutionStore` document under the same fresh state root and rejects malformed
or cross-book-inconsistent state before exposing the runtime. Callers can write
an explicit unclean checkpoint for restart evidence; persistent `shutdown`
writes a clean execution checkpoint before lifecycle finalization and converts
checkpoint failure into a failed shutdown rather than publishing a false clean
state. The books remain metadata/state seams only: AgentLoop execution,
provider/tool policy, PTY ownership, and TS/L2 routing are not granted by these
accessors.

The independent `recovery::RecoveryTrigger` now turns a validated execution
checkpoint plus lifecycle state into a side-effect-free `RecoveryDecision`:
fresh roots are `fresh`, clean halted roots are `resume_clean`, crashed roots
with unclean execution state are `recover_unclean`, and mismatches are
`reject`. `KernelRuntime::recovery_decision` exposes this read-only gate; it
does not recover sessions, rebind terminals, start workers, or select Python as
a fallback. Persistent runtime boot now retains `recover_unclean` and
`reject` as an explicit in-memory gate; `acknowledge_recovery` requires the
exact current decision before allowing boot. The acknowledgement performs no
rebind, checkpoint mutation, process/PTY fabrication, or fallback selection;
caller-owned recovery adapters still own those actions.

The runtime performance slice removes the former globally serialized admission
gate. A shared lifecycle barrier now protects active-state validation, process
reservation, task-book registration, and WorkerPool handoff. Boot takes the
exclusive side. Shutdown publishes `Draining` before waiting
for that exclusive barrier, so new admissions fail closed while approved work
drains. Registration is deliberately before direct
dispatch, closing the fast-completion state-overwrite race. Task records follow
the scheduler shard selection, and the benchmark-only observed entrypoint
times only contended lifecycle/task-book acquisition fallbacks. The isolated
`runtime.submit_reap` workload submits one bound Rust closure, waits, and
reaps per caller before admitting the next. On one Linux x86_64 release run
based at aligned tree `06e8288c`, each 4,096-item 1/2/4-worker, three-round
sample had zero errors/rejections and median throughput of about
18.1k/27.3k/32.1k ops/s. Aggregate WorkerPool claim/wake wait was
155.2/262.8/469.7 ms and p99 was 140/562/1,342 microseconds, while median
runtime-admission contention was zero. The result rules out promoting a
runtime-admission lock optimization as a general scaling policy and keeps
WorkerPool handoff as the next measured candidate. It does not create a Python
compatibility requirement or promote the Rust host to an L2/TS, AgentLoop,
provider, or production authority.

`KernelRuntime::reap_finished(max_tasks)` now supplies the matching bounded
reaper mechanism: it selects at most the caller budget, releases only terminal
task slots, and returns explicit pending/unavailable/error counts. A zero
budget is rejected. This is a caller-owned preparation for later shutdown and
recovery integration, not a background reaper or production authority.

The next bounded batch slice adds `submit_batch` and
`submit_batch_observed`. It reserves every generation-safe process handle and
records `Ready` state before handing the complete group to `WorkerPool`; a
reservation failure rolls back all previous reservations and executes no
closure. The fixed-work `runtime.batch_submit_reap` runner constrains each
caller to one submit/wait/reap group at a time and sizes process and queue
capacity to cover the maximum concurrent groups. It reports throughput in tasks
but p95/p99 in complete batches, a deliberately separate latency unit from
`runtime.submit_reap`. A local unpinned Linux x86_64 release sample on the
aligned tree with batch size 32 completed every 4,096-item 1/2/4-caller,
three-round case with zero errors/rejections: median throughput was about
363k/540k/591k tasks/s, aggregate queue wait was 5.4/8.7/18.7 ms, and
observed runtime-lock wait was 0/0.086/0.045 ms. A separately collected
single-task run on the same aligned tree was about 18.1k/27.3k/32.1k tasks/s
with 155.2/262.8/469.7 ms of aggregate queue wait. This is an unpinned
host-local admission comparison, not a linear
scaling or tail-latency claim, and does not add L2/TS, AgentLoop, provider,
PTY, Python-compatibility, or production-entry authority.

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
under `crates/l1-kernel-rs/tests/<domain>/` as independent Rust test targets.
The crate
contract-version check is part of `contract_vectors.rs`; no inline test module
remains in `lib.rs`. The worker scaling test uses only public submission and
shutdown behavior, so the clean-break public boundary remains explicit for
later TS and Rust runtime rebuilds.

The `sync` mechanism follows the same split: `tests/core/sync.rs` contains the
eleven public Mutex/Semaphore/Barrier/Condition/RWLock behavior tests, while
`tests/core/sync_vectors.rs` keeps the cross-language RWLock vectors. No private
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

### 4.7 终端探测与 Agent 进程硬约束

L1 的终端基础必须支持传统 OS 的命令终端，但不能把开发机的 shell 路径、
`PATH` 或默认终端写入内核。`terminal_probe` 因此采用两段式边界：宿主适配器
负责实际探测（例如 CMD、PowerShell 7、Bash、Git Bash 或其他 shell），将
可执行文件、调用参数前缀、版本、编码、交互/PTY 能力和可用状态注入
`TerminalObservation`；Rust 只校验、过滤和按显式配置选择候选。没有隐式
fallback，未选出可用候选时直接拒绝。

上层 Agent 进程通过 `process_constraints` 的声明式准入门进入托管进程域。
策略显式给出 ring、终端身份/类型、argv、cwd、环境键、超时、输出/CPU/内存
和进程组上限。`ProcessGroupRuntime::spawn_constrained` 先完成全部约束评估，
再校验适配器 executable/cwd/env 选项与声明一致，最后才把已批准 argv 交给
进程适配器；约束失败不会产生子进程，缺少 shell 命令正文也会拒绝。新增的
`spawn_gated_constrained` 在该路径前要求显式 `process.spawn` capability、匹配
gate/process 身份并执行 GateChain；GateChain 拒绝进入 gate ledger，关联不匹配则
在 ledger 前 fail-closed，均不会产生子进程。该入口目前是
Rust-native 机制候选，不接管现有 Python/L2 AgentLoop，也不声明 PTY、硬件
输入、生产 reaper 或 runtime cutover 权威。后续若要接入 TS/L2，只保留这组
版本化值合同，不复制 Python 的终端默认值或类布局。

进程生命周期 benchmark 同样不再在 runner 内推导平台 shell。`ProcessBenchmarkCommand`
只接受调用方注入的非空 direct argv；三个 benchmark binary 以自身 executable
和私有 child marker 构造显式 direct 命令，测试覆盖空 executable/空参数的
fail-closed 行为。这是测量脚手架约束，不是生产 runtime 的默认执行入口。
