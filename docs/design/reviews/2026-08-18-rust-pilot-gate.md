# Rust Pilot Gate Decision Record (2026-08-18)

> Status: blocked pending G3/G6. This record defines the semantic decisions
> that must be frozen before a Rust mechanism can receive runtime authority.
> Isolated Rust candidates are allowed, but this record does not authorize a
> runtime cutover or change the Python default path.

## Scope

The first migration review covers the mechanisms implicated by the fixed-work
preflight: EventBus dispatch/backpressure, synchronization, bounded worker
execution, lock IPC, and the append-only event journal. The review is
intentionally contract-first. Performance alone does not select a Rust
candidate when delivery, ownership, persistence, or execution semantics are
unresolved.

The isolated Rust synchronization slice now mirrors the five Python primitive
shapes (`Mutex`, `Semaphore`, `Barrier`, `Condition`, and `RWLock`) and passes
its own concurrency tests plus the Python contract regression slice. This is a
candidate implementation only; no runtime route or Port adapter points at it.

The following Python-only behavior is deliberately deferred from this slice:

- Mutex deadlock-cycle detection and the optional IPC lock channel;
- the bounded global named-object registry and eviction behavior;
- cancellation tokens crossing a lock wait;
- read-to-write upgrade policy, cancellation tokens, and FIFO reader ordering.

RWLock write reentrancy is now explicit: each language tracks a `writer_depth`
counter, and only the final matching unlock releases the writer. Empty owner
identities are rejected at the candidate boundary. The shared value fixture
locks these responses in both test suites; this does not authorize a runtime
pilot.

The isolated Rust process slice mirrors PCB snapshots, the declared lifecycle
FSM, cancellation flags/reasons, resource counters, and bounded process audit
rows. It deliberately leaves zombie-reaper scheduling, interrupt delivery,
allocator/limiter cleanup, and long-lived OS handles to the Python adapter
until those seams have language-neutral contracts.

The isolated Rust EventBus slice mirrors synchronous history insertion,
typed/wildcard callback snapshots, bounded in-flight delivery, explicit
submitted/completed/dropped counters, shutdown draining, and bounded dynamic
signal registration. Callback failures are contained at the candidate seam;
Python SSE/WS fan-out and event policy remain outside it.

The isolated Rust channel slice mirrors the JSON-safe `ChannelPort` behavior:
fixed capacity, blocking put/get with deadlines, overwrite-oldest mode,
peek/drain, close wakeups, and utilization. It does not accept arbitrary
interpreter objects or transport-specific framing.

The isolated Rust allocator/resource slice mirrors configuration-injected
allocation/free counters, expired and observe reclamation, bounded OOM victim
selection, pressure snapshots, swap accounting, profile limits, and cleanup.
It intentionally does not fire Python interrupts, terminate Python PCBs, or
append persistence records; those require language-neutral audit and lifecycle
ports before a pilot.

The ResourceLimiter sub-slice now consumes `kernel_resource_vectors.json` on
both sides. It freezes profile injection and fallback, signed check/release
costs, usage/all-usage reports, arbitrary-resource release, and cleanup. Role
configuration discovery and the allocator's OOM/interrupt/process side effects
remain Python-owned and are not pilot authority.

The isolated Rust WorkerPort slice mirrors bounded pending work, FIFO eviction
under backpressure, result-handle completion, panic-to-error conversion,
graceful draining, and idle shrink to the configured worker floor. It accepts
already-bound JSON-returning closures. Adaptive sampling, task argument
binding, cancellation/task timeouts, and Python exception mapping remain
outside this candidate and require a port-level decision before pilot routing.

The isolated Rust IPC slice mirrors lock message values, bounded historical
backlog, synchronous handler replies, request/response wakeups, timeout
cleanup, and resettable named-channel registration. It intentionally does not
open sockets, transfer interpreter objects, or decide cross-process ownership.

The isolated Rust journal slice mirrors the Python event row shape and
monotonic sequence contract with JSONL storage, batch append, type-filtered
queries, reopen recovery, and durable flush. It deliberately does not replay
events into Python process/device/interrupt state, replace SQLite in the
runtime, or decide checkpoint policy.

The isolated Rust audit/capability slice adds two adjacent mechanisms without
granting runtime authority. `AuditLog` retains a bounded chronological ring,
filters by agent identity, truncates detail, and can best-effort append
`audit.syscall` rows to the candidate journal while counting persistence
failures. `CapabilityAuthority` is the sole candidate invocation entry point:
unwired calls fail closed, wired executor panics become structured failures,
and successful or denied calls are audited. G1-G5 policy, boot wiring, and the
Python L3 executor remain outside this slice.

The isolated Rust GateChain slice is the first pure policy-engine candidate. It
consumes a frozen request snapshot and data-only thresholds, then emits
structured G1-G5 steps with stable `PASS`, `WARN`, `BLOCK`, and `REPORT`
values. It covers fail-closed whitelist, process/interactive identity,
boundary-safe territory, danger/frequency scoring, explicit G4 authorization,
and G5 reputation/history decisions. It deliberately does not load tools,
query posture/reputation/approval providers, emit events, or become an
execution authority.

The isolated Rust Constitution slice mirrors the pure rule/value layer. Rules
are serialized descriptors with stable severity and result enums; evaluation
uses an action-category index and explicit input snapshots for territory,
sandbox, constitution-file protection, scout restrictions, shared territory,
GateChain markers, and offensive-skill posture. Markdown parsing/rendering,
custom-rule persistence, skill lookup, posture lookup, and NMI/EventBus
emission remain outside the candidate.

The isolated Rust VFS slice mirrors only the provider-neutral filesystem
mechanism: a bounded mount table with longest-prefix resolution,
ring/read-only authorization, virtual-file storage, and TTL-bounded cache
invalidation for content supplied by an external provider. Real filesystem
access, system mounts (`/proc`, `/sys`, `/skills`, `/dev`), symlink/provider
policy, and adapter writes remain outside the candidate. Non-virtual operations
fail closed with `EADAPTER`; the slice does not inspect unmounted paths or
replace Python's VFS runtime.

The isolated Rust lifecycle/versioning/migration slice now mirrors the
provider-neutral lifecycle FSM, checkpoint record validation, Python's six
registered schema kinds, ordered JSON migration callbacks, and install-time
runner failure semantics. Python/Rust shared fixtures cover valid and invalid
state transitions, install/recovery decisions, stamping, identity migration,
future versions, and missing migration paths. It does not persist files,
generate authoritative timestamps, register settings, or run boot/install
side effects.

The isolated Rust platform slice mirrors host-provided OS values, shell and
grep command descriptions, URL joining, temporary-directory derivation, and
TCP endpoint parsing. `kernel_platform_vectors.json` covers POSIX and Windows
branches in both languages. It has no subprocess, directory, filesystem, or
socket side effects; those remain adapter-owned and are not pilot authority.

The isolated Rust paths slice mirrors deployment-mode defaults, explicit
overrides, child-path derivation, and resettable in-memory configuration.
`kernel_paths_vectors.json` covers CLI and Docker layouts. Environment/home
discovery and directory creation remain outside the candidate.

The isolated Rust territory slice mirrors component-aware lexical containment
with explicit working-directory input. `kernel_territory_vectors.json` covers
the Python boundary cases; filesystem and symlink resolution remain outside the
candidate and are not pilot authority.

The isolated Rust interrupt slice mirrors IRQ names, sequence numbers, payload
normalization, and bounded recent queries. `kernel_interrupt_vectors.json`
covers all five kinds and mixed history; callback dispatch, journal replay, and
process termination remain adapter-owned and are not pilot authority.

The isolated Rust errors slice covers built-in/default and unknown codes,
context/cause response fields, and explicit trace-id propagation. Locale
providers, ErrorBus capture, stack inspection, and persistence remain outside
the candidate and are not pilot authority.

The isolated Rust discovery slice mirrors the parsed configuration mechanism:
registered defaults and source snapshots, three-tier runtime state, object
shallow merge, scalar replacement, null-section retention, unknown-section
ignore behavior, runtime key updates, and tool/service fallback reads.
`kernel_discovery_vectors.json` is consumed by both languages. YAML parsing,
directory scanning, boot registration, logging, and Python singleton mutation
remain outside the candidate and are not pilot authority.

The 2026-08-19 contract re-audit found and closed one migration mismatch:
Python's install runner appends duplicate target-version registrations and runs
them in registration order; the Rust candidate now preserves that behavior and
has a matching regression test. Rust still exposes structured errors and owns
values rather than Python's exception/object-identity surface; an adapter must
map those details before any G6 pilot. File persistence, install authority,
and callback side effects remain Python-owned.

The isolated Rust load-adaptive slice mirrors the pure Python control law.
`kernel_load_adaptive_vectors.json` freezes EWMA, hysteresis, target-band
boundaries, growth/shrink clamping, slow-task `GROW_FAST`, cooldown, reset, and
stable decision reasons. It accepts an explicit timestamp and never samples a
clock, changes a worker pool, or reads the adaptive feature flag; those remain
Python/WorkerPort responsibilities and are not pilot authority.

The isolated Rust schema slice mirrors the kernel string-event registry:
owner-conflict rejection, same-owner replacement, sorted snapshots, membership,
and reset are covered by `kernel_schema_vectors.json`. It does not carry the L3
catalog or emit events; boot registration and event semantics remain outside
the candidate and are not pilot authority.

The isolated Rust rule-descriptor slice mirrors the pure value layer for
Constitution rules: severity conversion, PASS/WARN/BLOCK results, metadata,
sorted tags, explicit timestamps, and checker context. The shared
`kernel_rule_descriptor_vectors.json` covers serialization; callback ownership,
rule catalogs, Markdown/SettingsCenter I/O, and Constitution policy remain
outside the candidate and are not pilot authority.

The isolated Rust registry-base slice mirrors declarative registry values:
descriptor defaults, duplicate rejection/explicit overwrite, registration
order, category filtering, public serialization, and register/unregister
counters. The shared `kernel_registry_base_vectors.json` passes on both sides.
Handler closures, domain-specific registries, discovery, and runtime routing
remain adapter-owned and are not pilot authority.

The isolated Rust system-registry slice mirrors only name-sorted opaque section
snapshots and explicit summary aggregation. The shared
`kernel_registry_vectors.json` passes on both sides. Section producers,
module/process/device/syscall queries, clock reads, and runtime ownership stay
Python-owned and are not pilot authority.

The isolated Rust identity-UID slice mirrors prefix/length validation,
caller-supplied entropy candidates, bounded collision retries, reset, and
restore tracking. `kernel_identity_uid_vectors.json` passes on both sides;
random entropy, persisted bindings, and identity issuance authority remain
Python-owned and are not pilot authority.

The isolated Rust device slice mirrors explicit records, sliding rate windows,
strict degraded/down threshold transitions, counters, summaries, and aggregate
stats using injected time and policy. `kernel_device_vectors.json` passes on
both sides; provider connections, SettingsCenter defaults, health threads, and
system time remain Python-owned and are not pilot authority.

The isolated Rust SystemBus slice mirrors declarative component metadata,
in-place duplicate replacement, parent-available dependency filtering, stable
topological planning, cycle rejection, and explicit registration/inited/
started/stopped labels. `kernel_bus_vectors.json` passes on both sides.
Component callbacks, event routing, child-bus ownership, health/stats providers,
logging, and actual lifecycle side effects remain Python-owned and are not pilot
authority.

Those items are migration blockers for a runtime pilot, not reasons to expose
partial Rust authority. They must receive shared vectors or an explicit
versioned contract decision before routing is considered.

## EventBus contract

The current Python implementation establishes these observable rules:

1. Emitting a signal records history synchronously.
2. Listener callbacks are dispatched asynchronously through a bounded
   in-flight queue.
3. When the queue is full, the callback is dropped and `dropped` increases;
   the emitter does not block or raise solely because of overload.
4. `submitted + dropped` equals the callback dispatch attempts. After a
   draining shutdown, `completed == submitted` and `queue_depth == 0`.
5. A zero-drop run is the clean delivery baseline. Non-zero listener runs with
   drops are overload evidence and must not be reported as reliable throughput.

This means the Rust candidate must preserve explicit drop accounting and must
not silently turn a lossy overload path into an unbounded queue or an implicit
blocking policy. A future policy change requires a new contract version or an
explicit adapter mode.

## RWLock contract review

The Python implementation currently provides:

- shared readers and one exclusive writer;
- writer preference once a writer is queued;
- reentrant reads for the same agent, including while a writer waits;
- writer-to-read reentrancy for the current writer;
- ownership-checked unlocks;
- bounded acquisition using `timeout`.

The following points remain unresolved and therefore block pilot selection:

| Question | Current behavior | Required decision |
|---|---|---|
| Same-agent write reentrancy | The writer identity is reused, but no write depth is tracked | Reject explicitly, or add a depth counter and parity vectors |
| Read-to-write upgrade | Waits while the caller's read is held and eventually times out | Keep as an explicit unsupported operation, or define an upgrade protocol |
| Cancellation | No cancellation token crosses the lock API | Treat timeout as the only cancellation signal, or add a language-neutral token |
| Fairness | Writers are preferred; reader order is not FIFO | Freeze writer preference as the guarantee and leave reader order unspecified, or add FIFO sequencing |
| Empty owner identity | Empty strings can be passed as agent ids | Reject empty identities at the port boundary before a Rust pilot |

Until these choices have vectors on both sides, RWLock is only a provisional
performance candidate. The current evidence supports profiling it; it does
not authorize replacing it.

## WorkerPort contract review

The Python adapter currently provides:

- bounded pending work with FIFO eviction when the queue is full;
- deterministic completion for accepted, rejected, evicted, failed, and
  panicked result-handle tasks;
- graceful shutdown that drains accepted work and rejects later submissions;
- dynamic growth up to a configured maximum and idle shrink back to the
  configured minimum.

The Rust candidate preserves those mechanism-level rules for JSON values and
records `completed` and `rejected` counters. The following remain open before
an adapter can claim parity:

| Question | Candidate behavior | Required decision |
|---|---|---|
| Task cancellation | No token crosses `TaskFn` | Freeze timeout-only behavior, or define a shared cancellation token |
| Task timeout | No Rust-side forced termination | Keep timeout as caller-side waiting semantics, or define cooperative cancellation |
| Error mapping | Structured `TaskHandleError` | Define the Python exception/result mapping in the adapter contract |
| Adaptive control | Static grow-on-queue heuristic only | Keep adaptive sampling Python-owned, or version a metrics/control port |

Until these choices have vectors on both sides, WorkerPort is an isolated
candidate and not a runtime replacement.

## IPC and journal contract review

The Rust IPC candidate is intentionally limited to the in-process mechanism
that Python `ipc.py` exposes. Socket creation, framing, peer authentication,
and lock ownership across OS processes remain open seams. The journal keeps
the language-neutral event record and query semantics, but its JSONL backend is
not yet a drop-in replacement for Python's SQLite file and is single-instance
only. Before pilot routing, the adapter must choose one versioned persistence
format or provide a tested SQLite-compatible adapter, define cross-process
coordination and crash-tail recovery, and freeze replay authority.

## Gate status

- G2: contract snapshot, value/policy fixtures, lifecycle/versioning fixtures,
  discovery vectors, RWLock depth/identity vectors, and platform vectors are in sync. EventBus
  overload vectors cover counters, but callback ordering and overload policy
  remain bounded candidate semantics.
- G3: fixed-work Amdahl and lock evidence is reproducible, but queue overload
  policy and RWLock upgrade/cancellation/fairness semantics are open.
- G4: automation and side-channel boundaries are closed.
- G5: Rust/TypeScript build scaffolds and local checks are green.
- G6: blocked until one mechanism is selected, parity vectors are complete,
  and a feature-flagged rollback path is written. The WorkerPort slice is
  evidence for candidate review only; it does not close G6.
- The audit/capability slice is also evidence for contract review only. It does
  not close G1 or G6 until the Rust audit row vectors match Python persistence,
  executor registration is proven single-owner, and a rollback-capable port
  pilot exists.
- GateChain is contract evidence only until Python/Rust vectors cover every
  block and warning branch, provider inputs are authenticated at the adapter
  boundary, and a feature-flagged rollback path exists.
- Constitution is contract evidence only until custom-rule and built-in-rule
  vectors match Python, including category filtering and boundary-safe paths.
- The shared `kernel_policy_vectors.json` now covers stable GateChain and
  Constitution branches in both languages. It deliberately does not claim
  parity for provider side effects or the known Python `write_file` category
  gap; those remain pre-pilot review items.
- The shared `kernel_lifecycle_vectors.json` and
  `kernel_versioning_vectors.json` now cover the deterministic lifecycle and
  schema mechanisms. They are contract evidence only; persistence adapters,
  install authority, and runtime routing remain Python-owned.
- The shared `kernel_bus_vectors.json` now covers SystemBus metadata,
  registration order, parent dependency filtering, topology, cycle rejection,
  and state labels. It does not claim parity for callbacks, event delivery,
  child buses, health providers, or lifecycle side effects.
- The migration runner duplicate-registration behavior is now parity-tested on
  both sides; structured error mapping and callback side effects remain a G6
  adapter decision.

## Next permitted action

Add the missing Python vectors and their contract fixtures, rerun the bounded
EventBus and lock evidence, then record one candidate decision. Only after that
decision may a module-specific Rust pilot branch implement a mechanism behind
the existing Port with Python fallback.
