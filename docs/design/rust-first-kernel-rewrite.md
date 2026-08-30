---
pointer: DESIGN-2026-08-29-007
archive_number: DESIGN-2026-永久-107
fonds: DESIGN
year: 2026
retention: 永久
title: "Rust-First Kernel Rewrite Decision"
author: L3
formation_date: 2026-08-29
carrier: md
classification: 内部
pages: 881
archivist: L3
reviewer: L3
archive_date: 2026-08-29
source: design
keywords: [kernel, rewrite, readiness]
abstract: The future Praxis kernel is a clean-break Rust build, not a Python
series: active
date: 2026-08-29
status: active
construction: in_progress
---

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
`systems/rust-kernel-engine/l1-kernel-rs/src/substrate.rs`: typed generation-tagged process
handles, deterministic shard planning, and allocation-free atomic queue
metrics. The fixed-work benchmark schema is now present in
`systems/rust-kernel-engine/l1-kernel-rs/src/benchmark.rs`. The first Rust-owned state/queue
prototype is now present in `systems/rust-kernel-engine/l1-kernel-rs/src/state_queue.rs`, and
`systems/rust-kernel-engine/l1-kernel-rs/src/benchmark_runner.rs` provides a bounded-queue
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
`scripts/py/bench_r2_bundle.py` runs the independent Python reference under
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
The producer now counts workers parked in the queue wait while holding the
queue-lock boundary and limits notifications to actual idle waiters; active
workers therefore avoid no-op wake calls. The count is only a wake optimization
and never a correctness dependency, while shutdown continues to broadcast.
The single-result submission path also carries a typed admission outcome
directly to the `TaskHandle`, skipping an intermediate JSON/BTreeMap response.
The fire-and-forget wire boundary remains unchanged, and all rejection,
eviction, cancellation, deadline, and shutdown completion semantics stay under
the same evidence gate. `TaskHandle::done()` uses a release-published atomic
completion flag for lock-free polling; the result mutex and Condvar remain the
authority for value observation and blocking waits.
The Rust `agent_loop` candidate now provides the logical routing seam between
SessionBook truth and TerminalBook correlation. It validates
agent/cell/session/terminal identity, models loop lifecycle, and holds loop
state across each Session admission so stop and input/event writes are
linearizable. It intentionally does not execute AgentLoop provider/model/tool
work, prompt policy, PTY/subprocess I/O, terminal mailbox mutation, or WorkerPool
tasks; those remain adapter-owned. The independent `tests/session/kernel_test_agent_loop.rs` target
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
The independent target is `tests/runtime/kernel_test_agent_loop_execution.rs`.
The bridge also exposes `submit_input_batch`, which reserves all runtime tasks
before any worker can admit input. A capacity failure is therefore all-or-none
at the task boundary, including strict worker-queue capacity without evicting
older work; successful items still complete independently with the same receipt
and structured-failure contract. This is only a grouped execution mechanism
candidate and leaves provider, PTY, and production authority with the caller.

The next process-boundary slice is now present as the Rust
`process_adapter::ProcessAdapter` candidate. It implements only bounded
one-shot `ProcessPort` behavior: direct argv execution, or terminal-derived argv
from an injected `TerminalObservation`, optional cwd/input/environment values,
separately drained and retained stdout/stderr, deadline kill, and structured adapter errors. The
independent `tests/process/kernel_test_process_adapter.rs` target and the
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
`tests/process/kernel_test_managed_process.rs` target and `process.managed.lifecycle` fixed-work
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
`tests/process/kernel_test_process_bridge.rs` target and `process.bridge.lifecycle` fixed-work
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

`process_table_group_runtime::ProcessTableGroupRuntime` then composes the
group book with `ProcessTableBridge` rather than another standalone managed
process book. ProcessTable remains the only public child identity; bridge
snapshots provide bounded host metadata for adapter resolution, while a
terminal observation jointly reaps the host child and table row before the
group member is released. Capacity rollback uses the same joint cleanup. This
is still a caller-owned candidate and does not add PTY, signal, or background
reaper authority.

The same `ProcessTableGroupRuntime` now accepts `GatedProcessAdmission`: it
checks the `process.spawn` capability and correlated Agent identity, then
applies the existing hard process policy before invoking `ProcessTableBridge`.
Gate or constraint denial therefore records only gate evidence and creates no
ProcessTable row or host child; authorized work follows the joint reap path.

The follow-on audit wiring accepts a caller-owned `AuditLog` through
`ProcessTableGroupRuntime::new_with_audit`. Group creation, gate and constraint
decisions, bridge failures, successful admissions, and stop requests share one
bounded evidence path. Details contain only stable group/handle/count metadata;
argv, environment values, host PIDs, journal durability, and retention policy
remain outside the kernel candidate.

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
Callback panics are converted to structured adapter errors before they can
unwind the kernel boundary. This is a host-injection seam rather than a
platform implementation: Linux, Windows, PTY, permission, and retry behavior
remain outside the Rust crate.

`scripts/py/bench_r2_report.py` now summarizes that artifact by worker and
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

The follow-on `identity_binding::IdentityBindingStore` is the first durable
Rust metadata slice for this boundary. It writes a versioned
`BindingCheckpoint` containing only bounded identity-routing metadata, validates
the complete document before replacement, flushes a unique temporary sibling,
and restores the prior in-memory checkpoint when an atomic replacement fails.
Prompt fragments, Python persistence formats, cross-process locks, and
production identity authority remain outside the candidate; this closes only
the R4 metadata persistence mechanism.

The Rust `skill::SkillRegistry` is the next clean-break L1 mechanism slice for
the bounded portion of Python `SkillManager`. It owns typed skill metadata,
write-gated registration/replacement/deletion, builtin immutability, lifecycle
and posture/disclosure filters, agent/Cell/global scope, usage counters,
deterministic retrieval/listing, staged guidance and card completion, guidance
graph validation, virtual listing, and versioned in-memory checkpoints.
Admission truncates bounded fields and rejects unsafe content, NUL identities,
identity-less external writes, and invalid checkpoint references before
mutation. The shared skill vectors and independent policy target cover those
invariants, including concurrent access. Markdown/YAML discovery, prompts,
EventBus, R4 distillation/DPO, Card/TODO/AgentLoop strategy, API/L2Shell
surfaces, Python persistence, and production runtime authority remain host
responsibilities; no Python user-data compatibility is introduced.

The following R3 mechanism slice is the transport-neutral `network::PeerBook`:
clock injection, endpoint validation, timeout/loss/eviction state, and
deterministic snapshots are frozen, while socket/TLS/discovery and EventBus
delivery remain adapters.

The follow-on transport adapter now closes the Rust socket edge without
granting runtime authority. `transport::TransportAdapter` accepts explicit
deployment values, binds a bounded TCP JSONL listener and optional UDP
discovery pair, normalizes `from`/`to` messages into the retained `Message`
value, and exposes a fixed-capacity receive queue plus optional direct
handlers. Startup is transactional and stop/restart is serialized; malformed
frames, queue overflow, handler panics, and unsupported TLS are observable
fail-closed outcomes. The real-loopback integration target
`tests/network/kernel_test_transport.rs` covers the adapter boundary. This
slice deliberately does not import EventBus/card sync, probe the host for a
shell, own protocol-host routing, or become the Rust production entrypoint.

The next Rust L1 closure adds `syscall::SyscallDispatcher`, the clean-break
mechanism mapping for Python `l1.kernel.__init__.syscall()`. Requests are
validated for bounded operation names, caller identities, and nested JSON
arguments before handler lookup; the registration table is bounded and
deterministically ordered. Handler errors and panics become structured
failures and `EFAULT`, every attempt is recorded through the injected
`AuditLog`, and cumulative failure/panic/latency counters remain observable.
`SyscallResponse::to_wire()` preserves the retained top-level
`success`/`error`/`error_code` shape while preventing handler data from forging
control fields. Concrete process/event/resource operations remain host-injected
and must honor capability policy; this seam does not discover Python services,
select a shell, bypass `CapabilityAuthority`, or grant production authority.

The follow-on adapter slice changes handler lookup to a reader-writer lock:
dispatch readers share the table while registration remains exclusive. The
dispatcher now keeps a hash index keyed by shared `Arc<str>` names for the hot
lookup path and a separate ordered index for deterministic snapshots, avoiding
the old tree lookup on every dispatch without changing the wire contract. A
const-generic `register_batch` validates every name and the projected capacity
before publishing replacements or insertions, so a full table cannot leave a
partially wired host surface. Request validation counts serialized JSON through
a bounded writer rather than retaining a full argument buffer, so oversized
requests fail closed without a request-sized temporary allocation.
`syscall_adapters::KernelSyscallAdapters` then
provides an explicit, read-only runtime metadata registration for
`kernel.runtime.snapshot`, `kernel.runtime.recovery`, and
`kernel.capability.status`. These operations accept only `{}`, serialize
defensive snapshots, and never submit work or invoke a capability. The
non-persistent recovery read is an `EIO` failure, preserving fail-closed
semantics. Coverage lives in the independent
`tests/runtime/kernel_test_syscall_adapters.rs` target; process/event/resource
operation wiring remains a later capability-gated adapter decision.

The runtime observability follow-on adds `RuntimeObservation` and
`KernelRuntime::observation()`. It collects the `RuntimeSnapshot`, optional
persistent `RecoveryDecision`, `QueueMetricSnapshot`, and
`RuntimeLockWaitSnapshot` while holding the shared admission read barrier.
That linearization point prevents lifecycle/task admission from interleaving
with the read model, while the method remains side-effect-free and does not
perform recovery or any provider/tool/AgentLoop execution. Non-persistent
runtimes intentionally serialize `recovery` as absent; persistent runtimes
recompute the current decision from their Rust-owned execution checkpoint and
fail closed if it cannot be read. `kernel.runtime.observation` exposes this
aggregate as a separate syscall so the existing snapshot and recovery wire
contracts remain unchanged. The slice is an R4 read-model and future TS bridge
preparation only; production boot, cross-book recovery actions, and R5 cutover
authority remain open.

The next L1 lifecycle slice is the Rust-native `watchdog` evaluator. It
accepts an explicit `WatchdogPolicy`, host-supplied process observations, and
interrupt counts. Its process scan combines zombie counting and idle
ready/running detection in one pass; interrupt alerts retain deterministic
`BTreeMap` order and use strict `>` thresholds to match the Python watchdog
semantics. It returns only a versioned `WatchdogReport`, so hosts retain clock,
thread, ProcessTable/IRQ access, logging, signal, restart, and shutdown
authority. This closes the pure evaluation boundary of `os.py`, not the
production watchdog wiring or R4/R5 runtime cutover.

The lifecycle follow-on adds `os::OsCoordinator`, a Rust-native coordination
seam for the remaining `os.py` behavior. Host callbacks provide boot,
persistence, ordered shutdown hooks, terminal/Cell reset, and watchdog
observation; the coordinator owns only state transitions, bounded callback
waiting, restart sequencing, status snapshots, and a condition-variable
stop path for the optional watchdog loop. Callback errors and panics remain
observable, and a timeout never pretends to interrupt a callback that is
already running. The `get_os`/`reset_os` singleton is adapter-facing and does
not grant default-entrypoint authority. The independent
`tests/core/kernel_test_os.rs` target covers boot failure states, callback
ordering, timeout/panic reporting, restart, watchdog lifecycle, and singleton
reset. ProcessTable/IRQ discovery, logging, PTY/process-group shutdown,
Provider/AgentLoop wiring, and R4/R5 cutover remain outside this mechanism
candidate.

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
closed. Checkpoint generation is committed only after the lifecycle and
checkpoint writes succeed; failed transitions restore the prior in-memory
lifecycle/generation and roll back the lifecycle document when its paired
checkpoint write fails; failed renames remove their private temporary files.
Missing prior lifecycle bytes are removed during rollback, and a failed
restoration is surfaced as a dedicated `RollbackFailed` error rather than
silently accepting a split root.
No Python state, FFI, or Python boot authority crosses this seam.

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

The first T4b mechanism slice is `input_activity::HostInputActivityPort`.
`InputActivityHostAdapter` supplies explicit `Granted`, `Denied`, or
`Unavailable` permission and caller-timed aggregate samples. The port delegates
to the bounded Rust reducer, exposes denied/unavailable states without claiming
enablement, and stops the adapter on invalid samples. Device discovery, event
collection, permission UX, and monitoring policy remain host-owned; no raw
input or system clock crosses the Rust boundary. Permission revocation also
stops the adapter while retaining an explicit denied snapshot.

The T4b mechanism now also includes `CompositeInputActivityAdapter`. It
coordinates independently owned keyboard, pointer, or other aggregate-only
sources, keeps separately granted sources usable when one source is denied or
unavailable, and serializes source lifecycle calls. Invalid granted-source
failures and host callback panics remain fail-closed through the outer port;
platform discovery, permission UX, and monitoring policy stay outside Rust.

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
Each config/setting mutation uses a staged document and commits the in-memory
revision only after its atomic file replacement succeeds; a failed write
therefore leaves the prior value and revision available for a safe retry. The
explicit paired config/setting mutation stages both documents, restores the
first replacement if the second atomic rename fails, and reports rollback
failure instead of silently accepting a split root. The config adapter also
cleans failed rename temporaries.

The discovery candidate keeps the same adapter-owned three-tier semantics while
adding a Rust-owned admission seam: blank, NUL-containing, or overlong
section/key identities and invalid nested object keys fail closed before
mutation. `try_apply_document` validates the complete parsed document, applies
overrides to a staged registry copy, and commits once, preserving the previous
view on failure. `DiscoverySnapshot` and ordered section views are deterministic
read models for the future TS/L2 bridge; directory scanning, YAML parsing,
logging, and boot registration remain outside the candidate.

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
crosses this boundary. The independent `tests/session/kernel_test_execution_store.rs` target
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

If the subsequent clean `StateStore` commit fails, the runtime demotes the
execution document to an unclean checkpoint and best-effort records a crashed
state before returning the original state-store error. This closes the
cross-store ordering gap so recovery cannot observe a clean execution document
paired with a failed lifecycle commit.

The same persistent runtime now owns the assembly-selected `ConfigStore`.
`config_documents` is a defensive read model, while `set_config`,
`set_setting`, and `set_config_and_setting` provide explicit Rust-owned
mutation boundaries that publish snapshots only after atomic persistence
succeeds. Non-persistent runtimes fail closed instead of inventing a
configuration root; these methods do not reload providers or interpret Python
settings.
The persistent constructor opens and validates the configuration root and
execution checkpoint before performing unclean `StateStore` recovery. A
foreign or malformed attached root is rejected without advancing recovery
generation or mutating the existing lifecycle record, keeping root validation
side-effect-free.
The public checkpoint and recovery-decision reads share the runtime admission
barrier with lifecycle transitions. Shutdown and recovery acknowledgement call
internal helpers while that barrier is already held, preventing recursive-lock
deadlocks and cross-book observations during state changes.

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
recovery integration, not a background reaper or production authority. The
bounded prefix now carries each task's state from the same shard-lock snapshot
used for selection, removing the previous second lock/map lookup while keeping
stable shard/B-tree order and conservative concurrent-reap accounting.

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
under `systems/rust-kernel-engine/l1-kernel-rs/tests/<domain>/` as independent Rust test targets.
The crate
contract-version check is part of `contract_vectors.rs`; no inline test module
remains in `lib.rs`. The worker scaling test uses only public submission and
shutdown behavior, so the clean-break public boundary remains explicit for
later TS and Rust runtime rebuilds.
The build perimeter runs these targets as bounded parallel processes through
`scripts/py/run_rust_test_domains.py`; a single target remains available for
focused diagnosis, and no full-domain run is collapsed into one monolithic
process. Each target has a finite 300-second timeout by default. Expired
targets terminate their process group and become explicit failures, while
passing output stays compact unless `--verbose` is selected.

The `rule_descriptor` checker seam is fail-closed: an absent checker result
continues to mean PASS, but a panic from an injected checker is caught and
converted to BLOCK. This protects the policy value boundary without moving
Constitution providers, SettingsCenter discovery, or runtime authority into
the Rust candidate.

The registry-base notification hooks are advisory: a panic after a successful
registration or removal is caught and counted as `callback_errors`, while the
metadata mutation and registration order remain authoritative. This keeps
local observability failures outside the registry's core state contract.

The `sync` mechanism follows the same split: `tests/core/kernel_test_sync.rs` contains the
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

The follow-on `constitution_io` slice establishes the first Rust-owned
filesystem boundary without turning the Rust document into a Python
compatibility layer. `TerritoryConstitution` strictly parses the retained
territory/GateChain scalar shape, restores the rendered version header,
renders sorted deterministic Markdown, validates territory mutations, and
returns stable set-based diffs. `ConstitutionStore` serializes each complete
mutation under one store lock, flushes and atomically renames a sibling file,
and publishes the new in-memory snapshot only after the write succeeds;
temporary siblings use exclusive creation and the parent directory is synced
after rename where supported, so concurrent updates cannot reverse disk and
memory versions or silently clobber a sibling. Source, GateChain keys, and
selected paths reject embedded NULs before mutation. The independent policy
target covers malformed values, proposal merge, rollback, reopen, and
eight-thread version alignment. SettingsCenter discovery,
provider/prompt/EventBus wiring, and production Constitution authority remain
outside this candidate and still require R4/R5 evidence.

The EventBus candidate now uses signal type as a dispatch channel: at most one
callback task for a channel runs at a time, while workers scan past busy
channels to preserve cross-channel progress. This gives same-channel FIFO
without a global slow-callback barrier. The behavior is a Rust-native
mechanism invariant covered by blocking-callback tests; Python executor timing
and SSE/WS fan-out remain outside the rewrite boundary.
Custom signal registration rejects empty names before mutating the bounded
registry. Callback panics remain contained and are counted through the
Rust-only `callback_panics()` diagnostic; the shared Python/Rust
`EventBusStats` parity shape is unchanged.

The SystemBus candidate now rejects blank or NUL-containing component names
before mutating its metadata table. Its dependency planner builds reverse edges
once for a stable O(V+E) Kahn pass instead of rescanning every registered
component after each pop. Duplicate hard and optional declarations retain
their wire graph entries but are treated as one ordering edge, preventing a
false cycle while preserving registration-order tie breaking.
The registration table now keeps a hash index beside its ordered vector, making
replacement and direct metadata lookup O(1) without changing deterministic
registration order or dependency-plan output.

The string-event schema candidate now applies the same fail-closed identity
boundary to event names and owners: blank or NUL-containing values are
rejected before the owner map changes. Conflict rejection, same-owner updates,
sorted snapshots, and reset remain unchanged.

The lock-IPC candidate now counts contained handler panics through a
Rust-only `handler_panics()` diagnostic. Normal send/request behavior and the
shared `LockBus` statistics remain unchanged; socket transport and
cross-process ownership stay adapter-owned.

The synchronization candidate now assigns monotonically increasing tickets to
queued writers. A writer can acquire only when its ticket reaches the head;
timeout removal advances the queue and wakes successors. This closes writer
fairness independently of Python's condition-variable timing while preserving
the retained RWLock value vectors. The separate cancellation candidate adds a
cloneable one-way token, first-reason retention, cooperative checks, and
bounded waits; RWLock removes a cancelled writer ticket before waking
successors. Task/queue cancellation, cross-process lock ownership, and runtime
routing remain later mechanism work.
The optional priority-inheritance callback is advisory and is invoked behind a
panic boundary; a callback failure cannot poison the lock or cross the Rust L1
boundary.

The next settings slice reconstructs the Python L1 facade without carrying
Python state or class layout into Rust. `settings::SettingsRegistry` owns the
semantic default catalog and a bounded fallback map, while an injected
`SettingsProvider` is the explicit host seam for persistence and authorization.
The facade validates every key and complete provider snapshot before exposure,
supports single/batch writes, category reads, reset/reset-all, and preserves
the prompt-injection safety rule that malformed reads stay enabled. Provider
errors do not silently fall back to stale values. This closes the Rust-native
settings mechanism but not `ConfigStore` persistence, engineering-debug policy,
service hot reload, or R5 runtime authority; the independent
`tests/storage/kernel_test_settings.rs` target is the evidence boundary.

The next adapter slice now installs `settings_adapter::ConfigStoreSettingsProvider`
in persistent `KernelRuntime` instances. It overlays Rust defaults on the sparse
`settings.json` document and maps single, batch, reset, and reset-all operations
to atomic monotonic `ConfigStore` revisions. Non-persistent runtimes retain the
bounded fallback, while `settings_snapshot` and `set_runtime_setting` provide a
defensive runtime seam. The TS `RustSettingsProjection` is a read-only mirror
that validates source/revision/key/count bounds and rejects stale same-source
snapshots. This advances R4 adapter preparation but does not grant production
boot, AgentLoop/provider/tool execution, authorization, or R5 cutover authority.
The Rust adapter target is
`tests/storage/kernel_test_settings_adapter.rs`; TS coverage is
`tests/rust-settings-projection.test.ts`.

The follow-on protocol slice adds `settings_protocol::RuntimeSettingsEndpoint`
and an opt-in `HostRouter` binding for `settings_get`/`settings_set`. The endpoint
serializes a versioned `{operation, key, value, revision, source, values}`
reply from `KernelRuntime`, validates the JSON value bound, and records semantic
failures as result envelopes. Read/write authorization is an injected
`SettingsAuthorizer`; no approval field is accepted from the wire, and an
unwired endpoint fails closed. TypeScript accepts only successful Rust settings
replies through `parseRustSettingsReply`, while `ConfigReader` remains a local
read cache. This closes the R4 protocol adapter seam only; it does not wire the
production stdio host, GateChain policy, Python settings, or R5 cutover.

The next R4 host-composition slice adds
`protocol_host_runtime::ProtocolHostRuntime`. It combines the bounded JSONL
gate and `HostRouter`, centralizes the response-plus-ack policy, and keeps
router contract errors as structured denial envelopes while transport decode
errors remain transport failures. Host adapters can explicitly register command
executors and the settings endpoint through this object; the default
constructor still leaves both authorities unwired. `rust-protocol-host` now
uses the composition, but it does not infer a runtime, settings root,
authorization policy, or production boot configuration. The independent
`tests/runtime/kernel_test_protocol_host_runtime.rs` target proves settings
binding, fail-closed defaults, ack behavior, and the transport/semantic error
split. This advances R4 adapter wiring only; GateChain production identity,
real PTY/process ownership, AgentLoop/provider/tool execution, and R5 clean
cutover remain open.

The next host-bootstrap slice adds
`host_authorization::HostAuthorizationContext` and
`host_bootstrap::HostBootstrap`. The context is a bounded, host-injected
principal/session/ring/identity/debug record and is never accepted from wire
JSON. `HostBootstrap` validates every command name and optional authority
binding before assembling a strict `ProtocolHostRuntime`; a failed preflight
therefore cannot expose a partially wired router. Strict dispatch rejects
missing contexts and unverified contexts at ring two or above. Settings
adapters may override `SettingsAuthorizer::authorize_context` to consume the
full trusted record, while legacy principal-only authorization remains an
explicit fallback for non-strict adapters. The independent evidence target is
`tests/runtime/kernel_test_host_bootstrap.rs`. This is still R4 candidate
wiring: it does not promote the stdio host, grant engineering-debug authority,
start PTY/process-group or AgentLoop/provider work, or close R5.

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
