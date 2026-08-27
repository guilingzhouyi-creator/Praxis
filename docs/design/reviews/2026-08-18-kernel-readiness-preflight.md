# Kernel Rewrite Readiness Preflight (2026-08-18)

> Branch: `feature/root-kernel-preflight` after rebasing onto `main` at
> `55a3bd6`. This is a read-only readiness run; the corrected follow-up changes
> are limited to EventBus accounting and benchmark evidence; no Rust runtime or
> production mechanism source was changed in this historical run. Raw reports are kept in the ignored runtime directories
> `.praxis/evidence/kernel-readiness/20260818-preflight-01/` through
> `preflight-03/`.
>
> The follow-up semantic gate is recorded in
> `docs/design/reviews/2026-08-18-rust-pilot-gate.md`.

## 1. Gate result

| Gate | Result | Evidence / blocker |
|---|---|---|
| G0 source alignment | PASS for this run | Branch rebased onto current `main`; contract and roadmap documents are present |
| G1 authority/security slice | PASS (slice) | 41 targeted tests passed; full audit and 3.5 P1 closure remain open |
| G2 contract | PASS (snapshot) | `gen_kernel_contract.py` reported the snapshot in sync; golden-vector expansion remains open |
| G3 performance | **PARTIAL / BLOCKED** | Repeated Amdahl/lock reports are reproducible and EventBus now has normal/bounded evidence; candidate selection and overload policy remain open |
| G4 automation perimeter | PASS | Quality-configured sampling and stable L1 side-channel ports are implemented; focused automation/layer tests pass |
| G5 toolchain | PASS (scaffold) | Rust 1.97.1 and Node 24 build inputs are pinned; local Rust/TS smoke gates pass; no runtime authority added |
| G6 Rust pilot | BLOCKED | No candidate may be selected until G3 queue semantics are repaired and rerun |

## 2. Verification slice

Command:

```text
/home/guiling/dev/praxis/.venv/bin/python -m pytest -n 0 -q \
  tests/infra/test_single_execution_gate.py \
  tests/infra/test_kernel_contract_snapshot.py \
  tests/l1/kernel/test_capability.py \
  tests/l1/kernel/test_gatechain_identity.py \
  tests/l3/boot/test_boot_g1_whitelist.py \
  tests/l3/tool_system/test_harness_modes.py \
  tests/l4/api/test_auth_closed_default.py \
  tests/l3/tool_system/test_engineering_debug.py \
  tests/l3/tool_system/test_input_activity.py
```

Result: **41 passed in 1.71s** on Python 3.12.3 / WSL2. This confirms the
single execution seam, contract snapshot, G1/G2 behavior, closed-default API
authentication, harness posture checks, and the engineering-debug slices. It
does not close the full kernel audit or the 3.5 engineering-debug P1 list.

## 3. Performance evidence

Environment: Linux 6.18.33.2-microsoft-standard-WSL2, x86_64, 32 CPUs,
Python 3.12.3.

### 3.1 Fixed-work Amdahl

- Total work remained `200,000` at each worker count (1/2/4/8).
- Fitted serial fraction: `P=1.000`; the benchmark reports a saturated,
  high-serial profile.
- Throughput fell from `630,330 ops/s` at 1 worker to `502,198 ops/s` at 8.
- Queue p95 rose from `0.0753ms` to `0.4638ms`.
- The report's conclusion is to profile scheduler/shared-lock behavior before
  choosing a Rust target.

Raw report: `amdahl.json`.

### 3.2 Lock contention

- Mutex throughput fell from `1,079,868 ops/s` (1 worker) to `667,656 ops/s`
  (8 workers); p95 wait reached `0.0005ms`.
- RWLock throughput fell from `1,139,144 ops/s` to `16,537 ops/s`; p95 wait
  reached `0.8662ms` at 8 workers.
- Locked versus lock-free throughput was `7,370,253` versus `44,434,007`
  ops/s in this run.

RWLock/shared synchronization is a **provisional candidate**, not an approved
Rust pilot. The result needs a second run and a correctness/ownership review
before changing the synchronization mechanism.

Raw report: `lock.json`.

### 3.3 Queue and EventBus (initial run)

The reduced one-round run completed with:

- RingChannel put/get: `1,202,710 ops/s`;
- EventBus with 0 listeners: `933,307 ops/s`;
- EventBus with 4 listeners: `3,750 ops/s`;
- EventBus with 16 listeners: `896 ops/s`.

The run emitted **16,944** `too many in-flight tasks (500), dropping task`
warnings to `queue.stderr`. The result therefore measures a lossy, saturated
path, not reliable event delivery throughput. The drops are themselves a
readiness finding: the backpressure contract, drop accounting, and benchmark
success criteria must be made explicit before EventBus can be considered for
Rust migration.

Raw reports: `queue.json` and `queue.stderr`.

### 3.3.1 Corrected repeated run

The benchmark was corrected to use an isolated `EventBus` per sample, remove
listeners with `off_any(callback)`, drain the executor before sampling, and
record cumulative `submitted`, `completed`, `dropped`, and `drop_rate` values.
The corrected run used three rounds and retained one record per round:

| Listener count | Median emit ops/s | 3-round submitted | 3-round completed | 3-round dropped | 3-round drop rate | Status |
|---:|---:|---:|---:|---:|---:|---|
| 0 | 1,332,709 | 0 | 0 | 0 | 0% | clean |
| 4 | 4,583 | 117,553 | 117,553 | 2,447 | 2.0392% | lossy |
| 16 | 1,184 | 466,715 | 466,715 | 13,285 | 2.7677% | lossy |

RingChannel put/get was `1,389,096 ops/s`. Across all three rounds, stderr
contained 15,732 bounded-queue warnings. For every non-zero listener sample,
`submitted + dropped` equals the attempted callback count and, after the
draining shutdown, `completed == submitted`; all nine samples also reported
`queue_depth=0`. This confirms the accounting and listener lifecycle are stable,
but the configured workload still saturates
the bounded queue. The 4/16-listener figures are therefore explicitly
overload evidence, not a clean delivery baseline.

The same report also runs a bounded-load comparison at the registered
`EVAL_EVENT_BOUNDED_ITERS` setting (16 events per round):

| Listener count | Median bounded emit ops/s | 3-round submitted | 3-round completed | 3-round dropped | Status |
|---:|---:|---:|---:|---:|---|
| 0 | 1,273,480 | 0 | 0 | 0 | clean |
| 4 | 3,293 | 192 | 192 | 0 | clean |
| 16 | 2,372 | 768 | 768 | 0 | clean |

All bounded samples drained with `queue_depth=0`. This is a delivery
baseline under an explicit bounded workload; it must not be compared with the
normal curve without retaining the load setting.

Raw reports: `.praxis/evidence/kernel-readiness/20260818-preflight-02/queue.json`
and `queue.stderr` (ignored runtime evidence).

### 3.4 Platform microbenchmarks

| Primitive | ops/s |
|---|---:|
| mutex acquire/release | 1,415,234 |
| EventBus emit | 1,217,406 |
| RingChannel put/get | 1,374,345 |
| worker pool submit | 16,902 |
| thread create/join | 7,035 |

### 3.5 Repeated Amdahl and lock run

The follow-up run used three rounds on the same WSL2/Python environment and
kept fixed total work at every worker count. Amdahl remained fully serialized:

| Workers | Throughput (ops/s) | Queue p95 (ms) | Lock p95 (ms) |
|---:|---:|---:|---:|
| 1 | 484,702 | 0.0980 | 0.0007 |
| 2 | 521,416 | 0.1583 | 0.0006 |
| 4 | 509,858 | 0.2466 | 0.0005 |
| 8 | 446,942 | 0.5190 | 0.0005 |

The fitted serial fraction stayed `P=1.000`; measured speedup peaked at
`1.076x` with two workers and fell to `0.922x` at eight. The run completed
`200,000` work items at each point and emitted no benchmark stderr.

Lock contention remained sharply asymmetric:

| Primitive | 1 worker | 8 workers | 8-worker p95 wait |
|---|---:|---:|---:|
| Mutex | 1,102,046 ops/s | 889,321 ops/s | 0.0005 ms |
| RWLock | 932,619 ops/s | 16,156 ops/s | 0.8717 ms |

The locked microbench reached `7,438,225 ops/s` versus `41,573,343 ops/s`
lock-free (`0.179x` locked/lock-free ratio). RWLock/shared synchronization
remains a provisional hot-path candidate, but ownership, writer preference,
fairness, cancellation, and cross-language value semantics must be reviewed
before a mechanism change or Rust pilot.

Raw reports: `.praxis/evidence/kernel-readiness/20260818-preflight-03/amdahl.json`
and `lock.json` (ignored runtime evidence).

Raw report: `platform.json`.

### 3.6 Automation perimeter closure

The G4 follow-up moved sampler policy to
`config/quality/perf-harness.yaml` with strict missing/invalid-config
validation. The runner and manifest now resolve only L1 port contracts:
`ProcessPort`/`ProcessResult`, `TracePort`, `ObservabilityPort`, `EvidencePort`,
and `DependencyGraphPort`. Boot wiring supplies L3 adapters; standalone
`plan`/`doctor` retain no-op side channels and a local DAG planner.

Verification on Python 3.12.3 / WSL2:

```text
45 passed — automation manifest, harness, params, layer-import, and guard slices
```

`rg` confirms no `l3.*` import remains in `scripts/py/automation_manifest.py`
or `scripts/py/automation_runner.py`. This closes G4's authority-separation
criterion.

### 3.7 Toolchain scaffold closure

G5 now has a reproducible, build-only boundary:

- Rust `1.97.1` with `rustfmt` and `clippy` pinned by `rust-toolchain.toml`;
- contract-only `systems/rust-kernel-engine/l1-kernel-rs/` workspace with no Python bindings or
  execution authority;
- Node 24 CI pin, TypeScript 5.7/Vitest lockfile, and read-only
  `systems/typescript-shell-engine/` parity mirror;
- Makefile and CI gates for install, test, typecheck, format, and clippy.

Local verification passed: TS `5 tests`, TypeScript typecheck, Rust unit tests,
rustfmt, and clippy with warnings denied. G5 is complete as an environment
gate; G6 remains blocked until G3 selects a mechanism and writes parity,
feature-flag, and rollback evidence.

## 4. Decision and next gate

The evidence supports investigating shared synchronization and EventBus
backpressure as hot mechanisms. It does **not** authorize Rust implementation:

1. Decide whether the lossy 4/16-listener workload is an allowed overload
   outcome or a failed delivery invariant; keep the clean flag mandatory.
2. Review RWLock ownership/fairness/cancellation semantics and decide whether
   normal EventBus overload is an allowed outcome.
3. Write the M3 candidate decision record only after those decisions, then open
   a module-specific
   Rust pilot branch.

Until those steps are complete, keep Python as the only execution
implementation and treat the current results as preflight evidence, not a
baseline approval or a migration result.
