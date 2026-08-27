# Agent OS 3.x Closure and TypeScript Readiness Roadmap

> Status: in progress (P0.1 reference contract complete; TS mirror pilot)
> Audit basis: 3.0-3.5 implementation review, 2026-08-17/18
> Scope: production closure for the 3.0-3.5 chain and the prerequisites for a
> TypeScript L2/session rewrite. This roadmap is additive; it does not replace
> the L2 boundary, kernel boundary, or multi-language roadmaps.

## 1. Decision

The 3.0-3.5 chain is **partially implemented**, not production-complete.
The main execution path exists, but several state, persistence, observability,
and recovery contracts are still process-local or manually operated. These
gaps must be closed before a TypeScript client or session engine is allowed to
become a second authority.

Priority is therefore raised in this order:

1. **P0 — contract and recovery safety:** freeze the language-neutral data
   contract, make sessions uniquely addressable, and make persistence/recovery
   authoritative.
2. **P1 — production operation:** close cache durability, prompt outcome
   telemetry, skill-evolution transactions, canary rollback, and platform input
   failure handling.
3. **P2 — convergence and optimization:** centralize switches/configuration,
   remove semantic ambiguity, and harden parallel-test/restart behavior.

No TypeScript rewrite may promote a duplicate session, scheduler, AgentLoop,
tool pipeline, memory, or workflow authority. TypeScript is a projection,
dispatcher, and bridge client until every P0 gate is green.

## 2. Current 3.x status

| Area | What is already present | Closure gap | Priority |
|---|---|---|---|
| 3.0 memory/refinement | M1 filtering, M2 refinement, M3 R5/skill supply, M4 RC corpus | Refined records have no durable boundary; cache is process-local; some switches bypass the configuration center | P1 |
| 3.1 context compression | Compression, summaries, tool unloading, sensitive-data detection, recursion guards | `TieredCache` and derived artifacts do not survive restart; TTL/capacity/archive policy is not authoritative | P1 |
| 3.2 prompt lifecycle | Prompt Library, versions, AgentLoop injection | Monitor counts only explicit `get_prompt_monitored()` calls; production outcome and RC reporting are incomplete | P1 |
| 3.3 session system | Session/monitor/JSON/history/loader skeletons | Identity collision, reload reachability, unregister, sequence allocation, atomic persistence, and full recovery are incomplete | P0 |
| 3.4 skill evolution | R4Agent, failure traces, DPO feedback, candidate ledger, lifecycle states | JSON/generalized triggers are incomplete; candidate and `SkillManager` writes lack one transaction; canary rollback is manual | P1 |
| 3.5 engineering surface | Marker gate, engineering mode, API/L2 commands, prompt overlay | No real platform input adapter; provider start failure can leave state drift; defaults are duplicated | P1 |

The following observed behaviors are treated as release-blocking evidence until
fixed: two sessions can overwrite one terminal's `session_id`; `auto_reload()`
can return `IDLE` with no worker; ordinary prompt reads can evade monitoring;
and xdist can expose SQLite audit-journal lock contention.

## 3. Priority backlog

### P0 — contract, identity, and recovery (blocking)

> Arbitration (2026-08-22): `production-closure-roadmap.md` §3 mirrors this queue from its
> production-blind-spot panorama. THIS file owns slice-level execution for session identity /
> durable store / recovery (Slices A-F below); its P0.5-P0.8 (residual bypasses, scheduler
> enforcement, execution engine) stay there. Acceptance cross-checks exit criteria on both sides.

| ID | Work item | Required result | Dependencies |
|---|---|---|---|
| P0.1 | Freeze TS-neutral records | Versioned schemas for `SessionIdentity`, `EventEnvelope`, `SessionMessage`, `ToolFailure`, `DecisionSummary`, and `EvidenceRef`; deterministic JSON serialization and compatibility fixtures | None |
| P0.2 | Repair session identity | Separate `terminal_id`, `session_id`, and `process_id`; reject duplicate bindings; model create/attach/detach/close explicitly; preserve `user_id`, `role`, `cell_id`, and `memory_scope` | P0.1 |
| P0.3 | Make reload reachable | `auto_reload()` must rebuild workers and terminal bindings, restore a reachable `RUNNING`/`IDLE` state, and fail loudly when restoration is incomplete | P0.1, P0.2 |
| P0.4 | Implement durable JSON Store | Add schema version, atomic replace, journal/checksum, file lock, idempotent writes, corruption handling, and documented restore semantics | P0.1 |
| P0.5 | Unify input sequencing | Allocate `input_seq` exactly once at L3A ingress and carry it through conversation, thought, tool, and evidence records; replace temporary `sent_seqs` with a durable cursor | P0.1, P0.4 |
| P0.6 | Join persistence to recovery | Loader must reconstruct the complete session graph from the store, retain identity/scope fields, and make replay/recovery idempotent | P0.2-P0.5 |

P0 exit criteria: two concurrent sessions remain independently addressable;
restart/reload restores the same identity and cursor; a truncated or locked
store fails closed without silently losing records; protocol fixtures pass in
Python3 and the planned TypeScript mirror.

### P1 — production operation and lifecycle closure

| ID | Work item | Required result | Dependencies |
|---|---|---|---|
| P1.1 | Persistent `CacheStore` | Put tiered cache entries, summaries, tool results, and refined records behind one persistence interface with TTL, capacity, archive, and eviction metrics | P0.4 |
| P1.2 | Prompt production telemetry | Instrument the actual prompt read/injection path, record usage and outcome by version, and publish an RC-period report without exposing chain-of-thought | P0.1 |
| P1.3 | Skill-evolution transaction | Add commit/compensation semantics spanning candidate ledger and `SkillManager`; make generalized JSON triggers explicit and replay-safe | P0.4 |
| P1.4 | Canary automation | Define success/error/latency thresholds, automatic rollback, quarantine, and recovery evidence for evolved skills | P1.3 |
| P1.5 | Platform input adapter | Implement the real host input adapter behind a port; add unavailable-device and permission-denied states with deterministic fallback | P0.1 |
| P1.6 | Provider lifecycle rollback | On provider `start()` failure, restore the previous state and emit one traceable failure event; add restart and shutdown tests | P0.1, P0.2 |

P1 exit criteria: a process restart does not erase operational cache or prompt
metrics; a failed skill promotion leaves no half-committed state; canary
rollback is automatic and auditable; provider and input failures are visible
and recoverable.

### P2 — configuration and semantic convergence

| ID | Work item | Required result | Dependencies |
|---|---|---|---|
| P2.1 | Centralize runtime switches | Move module-level dictionaries and 3.x feature flags into `SettingsCenter` with defaults, validation, and restart semantics | P0.4 |
| P2.2 | Clarify refinement semantics | Document and test whether `MemoryRefinery.refine()` promotes immediately or only marks a candidate; preserve side-channel safety | P1.1 |
| P2.3 | Correct memory scope semantics | Make `memory_domain_filter` honor explicit scope and add cross-scope isolation tests | P0.2 |
| P2.4 | Remove duplicated prompt defaults | Keep one default source and make overlay precedence/version behavior explicit | P1.2 |
| P2.5 | Audit concurrency and restart tests | Add SQLite journal retry/locking coverage under xdist and repeat boot/reload cycles | P0.4, P0.6 |
| P2.6 | Keep CoT private | Exclude chain-of-thought from TS/API contracts; expose only `DecisionSummary` and `EvidenceRef` | P0.1 |

## 4. Dependency order

```text
P0.1 contract freeze
   ├── P0.2 identity/lifecycle ──┬── P0.3 reload
   │                             └── P0.6 recovery
   ├── P0.4 durable store ──────┬── P0.5 sequence/cursor
   │                             ├── P1.1 cache persistence
   │                             └── P1.3 skill transaction ── P1.4 canary
   └── P1.2 prompt telemetry

P0.1 + P0.2 ── P1.5 input adapter / P1.6 provider rollback
P0 exit ────── TS protocol mirror and L2 pilot
P1/P2 exit ─── production TS session rollout (after the L2 boundary roadmap)
```

Implementation is sliced into independently reviewable worktrees:

1. **Slice A:** P0.1 protocol records and compatibility fixtures. **Complete**
2. **Slice B:** P0.2-P0.3 session identity, lifecycle, and reload. **Complete**
   (`feature/s-session-identity` a7998e7d — additive terminal bindings,
   detach/close lifecycle, loud auto_reload with worker rebuild)
3. **Slice C:** P0.4-P0.6 durable store, sequence, and recovery. **Complete**
   (`systems/python-reference-runtime/l3/durable_store.py` DurableJsonStore + durable input-seq cursor +
   per-session snapshots joined to idempotent `SessionManager.recover_from_store`)
4. **Slice D:** P1.1-P1.2 cache and prompt telemetry. **Complete**
   (`TieredCache.save/load` durable mirror + eviction/expiry/hit metrics;
   versioned prompt-usage ledger with RC-period `prompt_usage_report`)
5. **Slice E:** P1.3-P1.6 evolution, canary, input, and provider lifecycle. **Complete**
   (`skill_promotion.py` transaction + canary quarantine; host input adapter
   with deterministic unavailable states; transactional provider enablement)
6. **Slice F:** P2 convergence and the TypeScript protocol mirror. A read-only
   mirror may start after Slice A; runtime replacement remains P0-gated.

Each slice is committed separately and must pass the relevant domain tests
before the next slice starts. Slices B and C may share no writer for the JSON
schema/store files; choose one owner for those files.

## 5. TypeScript rewrite gates

The TypeScript work may begin as a read-only protocol mirror after the P0
contract fixtures exist. It may not become the default L2/session runtime until
all of the following are true:

- P0.1-P0.6 exit criteria are met and the Python3 baseline is green.
- JSON Lines envelopes round-trip identically in Python3 and TypeScript,
  including unknown-field and version handling.
- Session recovery proves no duplicate `session_id`, no terminal overwrite,
  monotonic `input_seq`, and no lost acknowledged events.
- TS owns no scheduler, AgentLoop, tool execution, memory promotion, skill
  mutation, or workflow decision; those remain behind the existing bridge and
  capability gate.
- CoT is absent from public protocol types; only summaries and evidence refs
  cross the boundary.
- The L2 protocol, API manifest, and this roadmap agree on the same version and
  compatibility policy.

The following are explicitly **not** prerequisites for the first protocol
mirror: a Rust kernel, a second prompt provider, or a full frontend matrix.
Those remain governed by `frontend-kernel-roadmap.md`,
`kernel-boundary-audit.md`, and `multilang-migration.md`.

## 6. Verification and definition of done

Every P0/P1 slice must include focused tests plus the relevant baseline:

```bash
<main-tree>/.venv/bin/python -m pytest tests/l3/ tests/infra/ -x -q
<main-tree>/.venv/bin/python -m pytest tests/ -x -q
make lint
bash scripts/sh/verify-completion.sh
```

The full slice is ready to merge only when the worktree is clean, the
CompletionJudge reports `COMPLETE`, protocol/session/cache evidence is saved,
and the branch and main baseline are both green. After merge, use the mandated
dual-remote push flow; do not treat a passing protocol mirror as evidence that
the 3.x production closure is complete.

## 7. Related roadmaps

- `l2-multifrontend-session-layer.md` owns the L2 boundary and session protocol
  implementation after the P0 contract is stable.
- `frontend-kernel-roadmap.md` owns frontend variants and Rust migration timing.
- `multilang-migration.md` owns language backend registration and execution
  neutrality.
- `kernel-boundary-audit.md` owns the Rust kernel mechanism boundary.
- `docs/architecture/automation.md` owns the build/performance automation
  perimeter; automation remains an external consumer of versioned evidence,
  not a TS or kernel authority.

---

**Roadmap status:** P0 is the active implementation queue. P1 starts only after
P0 recovery evidence is green; P2 and TypeScript rollout remain downstream.
