# Rust-First Kernel Rewrite Decision

> Status: approved architecture direction; implementation remains isolated in
> the Rust build workspace until the rewrite checkpoints are complete.

## 1. Decision

The future Praxis kernel is a **clean-break Rust build**, not a Python3
drop-in replacement and not a user-data migration project. There are no
production users whose persisted Python3 state must be read by the new kernel.
The rewrite may choose new state directories, schemas, scheduling algorithms,
allocation strategies, error taxonomy, and internal APIs.

The current Python3 kernel is still useful as an architectural reference. It is
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
| Python3 behavior | Reference only | dict ordering, exception text, reaper timing, singleton layout |
| Performance workload | Must be reproducible, not byte-compatible | fixed work, queue pressure, lock contention, tail latency |

The existing `tests/fixtures/kernel_*_vectors.json` files therefore serve as
executable semantic baselines. A Rust redesign may reject a vector only after
recording the intentional semantic change, its security impact, and the new
Rust-native invariant. Passing a vector never authorizes FFI, boot wiring, or
runtime replacement.

## 3. Rust-Native Performance Shape

The rewrite is optimized around ownership and data movement, not around
mechanically reproducing Python3 classes:

1. Keep hot-path values typed and compact. Serialize to JSON or another wire
   format only at process/IPC/TS edges; do not put `serde_json::Value` in inner
   scheduling or accounting loops.
2. Use generational process handles and sharded tables so unrelated process
   operations do not contend on one global lock. Handle reuse must fail closed
   after generation rollover.
3. Use bounded per-core queues with explicit backpressure. Queue depth,
   rejection, wait time, and fairness are first-class counters rather than
   private executor state.
4. Keep policy evaluation pure and snapshot-driven. Providers, filesystem,
   model calls, prompts, DVG, R5/Mer, and AgentLoop orchestration stay outside
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
| R0 semantic map | Map Python3 modules to Rust responsibilities and mark preserved/redesigned/removed semantics | Every removed Python3 behavior has an owner or explicit non-goal |
| R1 native skeleton | Rust workspace with typed IDs, state ownership, bounded queues, wire adapters, and counters | `cargo test`, fmt, Clippy, and stress smoke are reproducible |
| R2 performance baseline | Rust fixed-work benchmark plus Python3 reference measurements | Throughput, p95/p99, CPU, memory, queue/lock waits, and drop counts are recorded |
| R3 mechanism closure | Process, event, allocator, capability, audit, persistence, and IPC mechanisms | Security vectors and Rust-native invariants are green; intentional divergences are documented |
| R4 kernel assembly | Rust-owned boot/config/state layout and versioned protocol boundary | No Python3 import or FFI is required by the new kernel |
| R5 clean cutover | New build entrypoint, fresh state initialization, recovery/rollback procedure | Cutover can start empty and recover from Rust-owned state without Python3 runtime authority |

The current branch is between R0 and R1. Its parity tests are evidence for
semantic mapping, not evidence that the final Rust kernel must retain Python3's
class layout or runtime behavior.

## 5. Immediate Work

The first R1 implementation slice is now present in
`crates/l1-kernel-rs/src/substrate.rs`: typed generation-tagged process
handles, deterministic shard planning, and allocation-free atomic queue
metrics. The fixed-work benchmark schema is now present in
`crates/l1-kernel-rs/src/benchmark.rs`. The first Rust-owned state/queue
prototype is now present in `crates/l1-kernel-rs/src/state_queue.rs`, and
`crates/l1-kernel-rs/src/benchmark_runner.rs` provides a bounded-queue
contention smoke that emits complete worker/round coverage with p95/p99,
queue/lock waits, and rejection counts. It must remain a build-only candidate
until R2 evidence exists. The `reputation` candidate now supplies a policy-
injected G5 score ledger without singleton, persistence, or provider authority.
The `notify` candidate now supplies a bounded side-channel buffer without
EventBus or transport authority. The repeatable report export slice is now
available with validated platform metadata and external-runner checks; the
`BenchmarkEvidence` envelope and `make rust-benchmark` exporter now provide
that slice. This remains R1 evidence only: CPU/memory sampling, Python3
reference comparison, and workload-specific drop analysis are still required
for R2. The first R3 mechanism closure slice is now the Rust-native
`identity_binding` metadata registry: it freezes the write gate, binding cap,
stable identity ID, revision, and snapshot invariants while explicitly leaving
prompt content, persistence, events, and API routing in adapters. No Python3
FFI, boot integration, Port replacement, or production state migration is part
of this work. Its shared vector intentionally covers only authorization and
mutation lifecycle, not prompt bytes, random UID bodies, or Python3 persistence.
The following R3 mechanism slice is the transport-neutral `network::PeerBook`:
clock injection, endpoint validation, timeout/loss/eviction state, and
deterministic snapshots are frozen, while socket/TLS/discovery and EventBus
delivery remain adapters.

The next assembly-preparation slice is the declarative `boot::BootPlan`. It
owns only validated step metadata, explicit replacement, a pre-execution lock,
and dependency-first ordering. Missing dependencies, invalid names, duplicate
registrations, and cycles fail closed. The shared
`kernel_boot_plan_vectors.json` fixture is consumed by Rust and Python3 tests;
Python3's historical omission of missing dependencies is recorded as an
intentional reference difference. This slice does not execute callbacks, read
configuration, start workers, mutate lifecycle state, or provide boot
authority. R4 still requires a separate Rust-owned config/state layout and
versioned protocol boundary.

The first concrete R4 state slice is `state_layout::StateLayoutManifest`.
It defines a new Rust-owned root with a versioned manifest, canonical relative
entries, parent-directory coverage, and explicit fresh-state paths. A
`StateProbe` supplied by the host is reduced to `initialize`, `resume`,
`recover`, `migrate`, or fail-closed `reject`. The candidate performs no
filesystem I/O, imports no Python3 state, and runs no migration callback; those
effects remain behind the future R4 adapter boundary.

The mechanism port boundary is now represented by `ports::PortRegistry` and
its value types. This preserves only deterministic descriptor registration and
the primitive `Result`/endpoint/message/input-activity shapes needed by future
adapters. Registration is explicitly locked before wiring; duplicate or
invalid descriptors fail closed. No Rust candidate in this slice opens files,
sockets, subprocesses, threads, or hardware monitors.

`assembly::KernelAssembly` now provides the first executable R4 seam by
composing the declarative boot, state-layout, port, and lifecycle candidates.
The standalone `rust-kernel` binary emits a deterministic JSON snapshot and
has no Python3 or FFI dependency. This is an assembly proof, not yet a complete
runtime: fresh-root creation, protocol serving, durable recovery, and provider
side effects are the next R4 obligations.
