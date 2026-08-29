---
pointer: DESIGN-2026-08-27-004
archive_number: DESIGN-2026-永久-104
fonds: DESIGN
year: 2026
retention: 永久
title: "Kernel Rewrite Readiness Package"
author: L3
formation_date: 2026-08-29
carrier: md
classification: 内部
pages: 391
archivist: L3
reviewer: L3
archive_date: 2026-08-29
source: design
keywords: [kernel, rewrite, readiness]
abstract: Rust is the approved direction for a clean-break, Rust-first kernel build.
series: active
date: 2026-08-29
status: active
construction: in_progress
---

# Kernel Rewrite Readiness Package

> Status: review-ready; no Rust runtime authority or production mechanism
> implementation is included in this package. The Rust workspace contains
> contract/value types and isolated mechanism candidates, including the
> bounded WorkerPort, lock IPC, event-journal, bounded-audit, and
> capability-authority and GateChain slices.
> The pure Constitution rule/evaluation slice is also isolated; no Rust
> runtime authority is included. The health-result aggregation slice is also
> isolated; runtime probes remain Python-owned. The memory-ring swap planning
> slice is likewise isolated; ring mutation remains Python-owned.
> The system-registry value slice is also isolated; section producers and
> runtime queries remain Python-owned.
> Baseline: `main` at `55a3bd6` (2026-08-18). The package turns the
> kernel boundary audit and Rust-first roadmap into entry gates for the first
> native Rust substrate and eventual clean cutover.

## 0. Decision to hold

Rust is the approved direction for a **clean-break, Rust-first kernel build**.
This package is still preflight: it does not grant the isolated candidate
workspace runtime authority, Python FFI, or permission to read old Python
state. The future kernel may choose new state layouts, schemas, schedulers,
allocators, and internal APIs because there are no production users whose data
must remain compatible.

Python remains the semantic reference for the R0 mapping phase. Its behavior is
not automatically a Rust requirement. The current execution seam
(`invoke_capability`) and contract snapshot are useful evidence, but the first
Rust-native substrate is blocked until the gates in this document and the
Rust-first architecture decision are evidenced.

### 0.1 Shared vectors are semantic evidence

The shared vectors are not a user-data migration suite. They freeze only the
security and control invariants that must survive an architecture rewrite:
fail-closed decisions, lifecycle terminality, audit causality, boundedness,
and explicitly retained wire fields. Python-specific exception text, dict
layout, singleton ownership, reaper timing, and internal data structures may
be redesigned. An intentional vector divergence must be recorded with the new
Rust invariant and its security/performance rationale.

See `docs/design/rust-first-kernel-rewrite.md` for the R0-R5 clean-break
architecture and performance gates.

## 1. Evidence snapshot

| Area | Current evidence | State before this package closes |
|---|---|---|
| Boundary audit | Kernel Boundary Integrity Score `42/100`; direct upper-layer imports and historical bypasses are documented | **Reverify** after the merged hardening slices |
| Single execution authority | `l1.kernel.capability.invoke_capability` is present; boot is the only executor wiring point; unwired calls fail closed and audit | **Reverify** with static and runtime tests |
| Gatechain | Boot populates the G1 whitelist; high-ring identity and closed-default API authentication have code and tests | **Reverify** in the current environment |
| Process/audit/event seams | Process FSM, cancellation, persistent Python audit, event schema, scheduler port, and contract snapshot are present; Python/Rust now consume a shared process lifecycle/resource/audit fixture; Rust bounded audit remains isolated with optional journal wiring | **Reverify** for parity and persistence |
| Capability authority | Python `invoke_capability` is the runtime seam; Rust now has an isolated fail-closed authority with panic conversion and per-call audit | **Reverify** against the Python gate and boot wiring |
| GateChain candidate | Rust mirrors pure G1-G5 inputs, four-state steps, and bounded history; providers and policy remain adapter-owned | **Green fixture; expand before G6** |
| Constitution candidate | Rust mirrors rule descriptors, category filtering, territory/sandbox/scout checks, and explicit posture inputs; file IO and side effects remain outside | **Green fixture; expand before G6** |
| Discovery candidate | Rust mirrors defaults/source/runtime layers, parsed section merging, null retention, runtime updates, and tool/service fallbacks; YAML/filesystem/boot discovery remain Python-owned | **Green fixture; candidate-only** |
| Policy parity fixture | `tests/fixtures/kernel_policy_vectors.json` is consumed by Python and Rust GateChain/Constitution tests for stable block/pass branches | **Green; expand before G6** |
| Kernel contract | `docs/contracts/kernel-contract.json`, contract generator, and snapshot test exist at contract version 1 | **Freeze** only after a clean regeneration/diff review |
| Engineering debug mode | Main feature is merged, but the roadmap still has P1 gaps: settings authorization bypass, hardware adapter absence, provider rollback, production prompt read exposure, and privacy-config drift | **Open P1** |
| Performance decision | Runs `20260818-preflight-01` through `20260818-preflight-03` have fixed-work Amdahl/lock/platform evidence, explicit EventBus dispatch/drop counters, and separate bounded clean-load evidence; normal non-zero listener loads remain lossy and RWLock needs ownership review | **Open M3** |
| Automation perimeter | Quality sampling is configured outside L1; stable evidence/observability/dependency-graph/trace seams are present on the preflight branch | **Reverify** with the runner gates |
| Build scaffolding | `systems/rust-kernel-engine/Cargo.toml`, `rust-toolchain.toml`, `systems/typescript-shell-engine/package.json`, lockfile, and TS config are present on the preflight branch | **Reverify** with language-check |

The historical implementation ledger in
`docs/design/rust-readiness-hardening-plan.md` marks WS1–WS6 slices as landed.
This package treats those marks as implementation evidence, not as a substitute
for re-running the acceptance gates.

## 2. Boundary freeze

### 2.1 Minimal kernel mechanisms allowed to sink

The Rust candidate may contain only mechanism and invariant enforcement:

- synchronization, event/channel primitives, and ordering guarantees;
- process table, lifecycle FSM, cancellation token, and owned handles;
- allocator/resource accounting and bounded worker submission;
- constitution and gatechain engines, with policy thresholds supplied as data;
- `invoke_capability` registration, authorization, invocation, and audit;
- append-only audit, checkpoint/restore, IPC primitives, paths/platform seams;
- versioning/migration and primitive-only Port value types.

### 2.2 Explicitly outside the Rust kernel

Prompts, skills, model/provider registry, commands, cards/issues, tool
discovery policy, approval policy, harness/security-mode policy, reputation,
identity-binding policy, DVG business planning, R5/Mer semantics, and the
automation/performance runner remain in Python/config/build tooling.

Engineering debug mode is an L3 policy. L1 exposes only its language-neutral
primitives (`InputActivityPort`, event/channel, audit, and capability seams);
L1 must not inspect the marker file or decide whether a caller is a developer.

### 2.3 Non-negotiable invariants

1. Every external capability invocation enters one execution authority.
2. Unknown capabilities, empty G1 registration, missing identity, failed
   posture checks, and missing wiring fail closed.
3. Every accepted or rejected invocation produces a durable audit record.
4. A terminated or cancelled process cannot execute another capability.
5. Resource accounting and event ordering are explicit and bounded.
6. No interpreter-specific object crosses a Port or language boundary.
7. The new Rust kernel can start from a fresh state root and recover its own
   versioned state without importing Python runtime objects or old user data.

## 3. Readiness gates

### G0 — Governance and source alignment (P0)

**Purpose:** establish a reproducible baseline before measuring or migrating.

Required evidence:

- clean dedicated worktree and branch, with the current main commit recorded;
- implementation ledger, architecture docs, contract snapshot, and roadmap
  statuses agree about what is landed versus merely planned;
- no generated count or baseline is hand-edited;
- the CompletionJudge and normal repository gates are run at the final
  preflight checkpoint.

Exit condition: this package, the roadmap, and the hardening plan all point to
the same gate status.

### G1 — Authority, security, and audit (P0/P1)

Required evidence:

- static single-execution-gate test passes and no boundary handler bypasses
  `invoke_capability`/`invoke_gated`;
- G1 whitelist is non-empty after boot; unknown capability is BLOCK;
- G2 identity, API authentication, harness posture, and ring checks fail
  closed when their provider or wiring is unavailable;
- process cancellation and terminal state prevent later invocation;
- accepted and rejected calls are present in the durable audit journal;
- 3.5 P1-A through P1-E are either fixed and tested or explicitly approved as
  a release blocker. In particular, generic settings must not mutate the
  `engineering_debug.*` namespace without the developer gate.

Exit condition: the audit §4 invariant checklist is green on current main,
not only on the historical hardening branch.

### G2 — Contract freeze (P0)

Required evidence:

- regenerate `docs/contracts/kernel-contract.json` and review the diff;
- keep the contract version and public names intentional; remove accidental
  exports before freezing;
- freeze primitive value types (`ProcessResult`, `ProcessOptions`, `Event`,
  error kinds, and Port snapshots);
- classify retained wire fields versus redesignable Python behavior; define
  versioned serialization, ordering, cancellation, and timeout semantics only
  for boundaries that the new kernel keeps;
- add golden vectors for success, denial, unwired executor, cancellation,
  timeout, and restart/recovery cases.

The shared value fixtures include
`tests/fixtures/kernel_value_vectors.json` for process success/timeout, options,
lifecycle states, Signal/Event records, EventBus clean/lossy counters,
fail-closed capability results, and RWLock ownership. The platform fixture
`tests/fixtures/kernel_platform_vectors.json` covers pure POSIX/Windows command
and endpoint values. Cancellation and restart/recovery vectors remain open G2
items.

The process-table fixture
`tests/fixtures/kernel_process_vectors.json` additionally freezes PID/PCB
registration, READY/RUNNING transitions, identity verification, cancellation
terminality, exit-to-ZOMBIE and reap, resource totals, and audit order. It
intentionally omits wall-clock fields and Python-owned reaper, interrupt,
allocator/limiter cleanup, and OS-handle side effects.

The paths/platform candidates are deliberately split at the side-effect
boundary: Rust transforms explicit snapshots into command and path values,
while Python retains environment discovery, filesystem layout, subprocess
execution, and socket lifecycle.

The territory candidate follows the same boundary. Its lexical containment
function consumes explicit paths and an optional working directory, rejects
component-prefix collisions, and does not resolve filesystem state or symlinks.
`kernel_territory_vectors.json` is the shared Python/Rust parity baseline.

The interrupt candidate is similarly value-only: `InterruptType`, history rows,
per-kind sequence accounting, and bounded queries are covered by
`kernel_interrupt_vectors.json`. Handler callbacks, signal/event emission,
durable replay, and cancellation/termination remain outside Rust authority.

The errors candidate freezes the code/message catalog and response shape while
leaving localization, stack/source extraction, ErrorBus capture, and durable
logging to adapters. `kernel_error_vectors.json` is the parity baseline and
trace ids are accepted only as explicit caller-provided values.

The discovery candidate freezes only the parsed configuration value contract.
`kernel_discovery_vectors.json` covers registered defaults, source snapshots,
object shallow merge, scalar replacement, null-section retention, unknown
sections, runtime overrides, and tool/service fallback reads. Directory scans,
YAML parsing, warning/logging, boot registration, and mutation of the Python
singleton remain adapter-owned.

The SystemBus candidate freezes component metadata, parent-available dependency
filtering, registration order, stable topology, cycle errors, and lifecycle
labels in `kernel_bus_vectors.json`; callbacks, child-bus routing, and actual
lifecycle side effects remain Python-owned. The ResourceLimiter candidate uses
`kernel_resource_vectors.json` for injected profiles, fallback lookup, signed
check/release costs, usage snapshots, unknown-resource release, and cleanup;
role discovery and allocator/process side effects remain adapter-owned.

The health candidate uses `kernel_health_vectors.json` for explicit subsystem
status aggregation, failure/degraded precedence, counts, retained details, and
elapsed-time rounding. It never imports modules, reads clocks, probes
singletons, emits logs, or decides runtime health; those remain Python-owned.

The swapper candidate uses `kernel_swapper_vectors.json` for importance-based
ring routing, expired short-ring compaction, and pressure action flags. It does
not touch MemoryService, allocator sampling, clocks, worker threads, or
persistence; those remain Python adapter responsibilities.

The registry candidate uses `kernel_registry_vectors.json` for deterministic
section snapshots and explicit summary aggregation. It accepts only JSON
sections, module status values, counts, syscall names, and caller-supplied
timestamps; section writes, provider queries, syscall discovery, and singleton
ownership remain outside the Rust candidate.

The tool-chain candidate uses `kernel_tool_chain_vectors.json` for stable
call-field normalization, HMAC-SHA256 truncation, `GENESIS` fallback, and
root-first fingerprint-chain verification. Key provisioning, call storage,
trimming/re-rooting, and execution remain Python adapter responsibilities.

The synchronization candidate additionally consumes `kernel_sync_vectors.json`
for reentrant reads, zero-timeout writer failure, status snapshots, and
missing-owner unlock errors. It does not freeze queued-writer fairness,
cancellation, cross-process ownership, or runtime lock routing.

The deterministic EventBus slice uses `kernel_event_vectors.json` to freeze
bounded history retention, type-filtered history, signal serialization, and
idle dispatch counters with no listeners. Callback scheduling, overload drops,
shutdown fairness, and runtime fan-out remain performance or adapter evidence.

Exit condition: a Rust implementation can implement the contract without
importing Python or L3 policy modules.

### G3 — Performance evidence (M3, P0 before Rust code)

Run on the reference WSL platform with the repository virtual environment and
record the exact commit, Python version, dependency lock, CPU, memory, and
load conditions. Store untracked evidence under
`.praxis/evidence/kernel-readiness/<run-id>/`.

Minimum run set:

```text
<main-tree>/.venv/bin/python tests/benchmarks/bench_scale.py \
  --mode amdahl --agents 1,2,4,8 --json <run>/amdahl.json
<main-tree>/.venv/bin/python tests/benchmarks/bench_scale.py \
  --mode lock --json <run>/lock.json
<main-tree>/.venv/bin/python tests/benchmarks/bench_scale.py \
  --mode queue --json <run>/queue.json
<main-tree>/.venv/bin/python tests/benchmarks/bench_platform.py \
  --json <run>/platform.json
```

The report must prove fixed total work at every worker count and retain:

- throughput and operation latency, including p95 batch latency;
- fitted Amdahl serial fraction `P` and speedups for 1/2/4/8 workers;
- scheduler queue wait, lock wait, saturation knee, CPU, memory, and variance;
- benchmark errors, missing counters, and platform metadata.

Synthetic sleep/hash workloads, per-worker duplicated total work, or copied
example numbers are not migration evidence. Select a Rust candidate only when
the measured serial/queue/lock profile predicts a meaningful mechanism-level
benefit. A low `P` or LLM-dominated run is a valid result: defer Rust rather
than forcing a migration.

### G4 — Automation and evidence perimeter (P1)

Before M3 is accepted:

- move `PERF_HARNESS_*` sampling defaults out of L1 mechanism params into the
  quality/build configuration;
- make runner execution depend only on `ProcessPort`/`ProcessResult`;
- expose stable evidence, observability, and dependency-graph ports instead of
  importing L3 implementations from build scripts;
- keep automation manifests, DVG plans, evidence reports, and performance
  results outside the Rust kernel and L2 session authority;
- keep L2 protocol measurements separate from fixed-work L1 migration evidence.

Exit condition: replacing the Python process adapter or DVG implementation
does not change the manifest schema or report consumers.

### G5 — Toolchain and packaging (P1)

No language implementation is started until the environment decision is
recorded and reproducible:

- pin supported `rustc`/`cargo`, formatter, clippy, and target triple;
- pin the supported Node/TypeScript toolchain for the protocol mirror;
- decide whether Rust/TS manifests live in a new build-environment subtree;
- provide offline/CI smoke commands and artifact locations;
- keep Python's current test and runtime path usable during the migration.

The build boundary is now checked in: `systems/rust-kernel-engine/Cargo.toml` and
`systems/rust-kernel-engine/l1-kernel-rs/` are contract/candidate Rust scaffolds, while
`systems/typescript-shell-engine/` is a read-only protocol parity mirror with a committed
lockfile. `rust-toolchain.toml`, Makefile targets, and
`.github/workflows/multilang.yml` pin and exercise the same checks. These files
do not grant Rust or TypeScript runtime authority.

### G6 — Clean cutover and recovery (P0 for the new kernel)

For the selected Rust-native mechanism, require a semantic reference run and a
Rust-native run against the classified vectors. The cutover must have:

- zero contract, audit, security, or state-machine mismatches;
- no unexplained invariant mismatch; any intentional divergence is recorded;
- repeated fixed-work samples supporting the claimed throughput and tail-latency
  result;
- a fresh-state bootstrap, recovery procedure, and source-level rollback point;
- a documented cutover abort trigger for correctness, audit loss, tail latency,
  memory, or platform-specific failures. A Python runtime fallback is optional,
  not a compatibility requirement.

## 4. Workstreams and deliverables

| Workstream | Priority | Deliverable | Blocks |
|---|---|---|---|
| WS-A status reconciliation | P0 | Current-main evidence matrix; corrected plan/roadmap statuses | All gates |
| WS-B authority and 3.5 closure | P0/P1 | Single-write authorization, production prompt redaction, input privacy/provider fixes, regression matrix | G1 |
| WS-C contract freeze | P0 | Contract v1 review, golden vectors, compatibility rules | G2/G6 |
| WS-D performance baseline | P0 | Fixed-work Amdahl/lock/queue/platform JSON plus decision record | G3 and candidate selection |
| WS-E automation perimeter | P1 | Quality config and stable evidence/observability/DVG seams | G4 |
| WS-F toolchain plan | P1 | Rust/TS version matrix, manifest location, CI/offline smoke design | G5 |
| WS-G migration decision | P0 after G3 | One selected mechanism, non-selection rationale for others, rollback plan | First Rust implementation |

## 5. First Rust pilot selection rule

The candidate is not chosen by module popularity or line count. After G3,
record a decision with this minimum shape:

| Field | Required value |
|---|---|
| Candidate mechanism | One of sync/event/process/allocator/worker/IPC, or an evidence-backed alternative |
| Serial fraction | Measured `P` with fit quality and worker sweep |
| Contention | Queue and lock wait distributions |
| Contract seam | Port/capability name and frozen value types |
| Expected benefit | Why Rust can change the measured bottleneck |
| Exclusions | Why prompts, policy, DVG, automation, or LLM paths are not candidates |
| Rollback | Feature flag, fallback implementation, and trigger thresholds |

If no candidate meets the evidence threshold, the correct outcome is
`Rust deferred; Python retained`, with the report preserved for the next
review cycle.

## 6. Ready-to-start checklist

Rust mechanism implementation may begin only when every item is checked:

- [ ] G0 source and documentation statuses reconciled.
- [ ] G1 current-main security, bypass, process, and audit tests are green.
- [ ] 3.5 P1 gaps are closed or explicitly accepted as blockers; none are
      silently carried into the kernel contract.
- [ ] G2 contract snapshot and golden vectors are reviewed and versioned.
- [ ] G3 fixed-work evidence exists with platform metadata and no invariant
      violations.
- [x] G4 automation/build dependencies no longer establish L1 authority.
- [x] G5 Rust/TS toolchain and packaging decisions are reproducible.
- [ ] G6 one Rust-native cutover, semantic vectors, fresh-state recovery, and
      rollback point are written.
- [ ] `gate-merge.sh completion` reports `COMPLETE` for the preflight branch.

Until this checklist is complete, work remains in the preparation phase. The
permitted work includes contract/value mirroring and isolated mechanism
candidates, plus evidence and decision records; no Rust mechanism may receive
runtime authority and no broad kernel rewrite may begin.
