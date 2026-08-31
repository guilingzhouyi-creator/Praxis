---
pointer: ROADMAP-2026-08-30-012
archive_number: ROADMAP-2026-长期-012
fonds: ROADMAP
year: 2026
retention: 长期
title: "L3 TypeScript rewrite — Agent coordination over Rust execution"
author: L3
formation_date: 2026-08-30
carrier: md
classification: 内部
pages: 24
archivist: L3
reviewer: L3
archive_date: 2026-08-30
source: roadmap
keywords: [typescript, agentloop, rust, l3]
abstract: "Build the clean-break TypeScript L3 coordination layer while Rust remains the L1 execution authority."
series: active
date: 2026-08-30
status: active
construction: in_progress
---

# L3 TypeScript rewrite — Agent coordination over Rust execution

> Status: P0 contract/ingress, the first three P1 boundary slices, the first
> P2 Card/Scheduler and AgentLoop/Cell slices, the L3A peer/replay recovery
> slice, and the bounded L3B cross-Cell routing slice are implemented on
> `feature/l1-rust-host-bootstrap` (TS L2 intent → detached provider
> context/tool projection → TS L3 coordinator → bounded Card/Scheduler,
> AgentLoop/Cell, peer/replay, and cross-Cell routing ports → Rust protocol
> execution port). The public `L3Coordinator` facade, bounded coordinator
> route evidence, and host composition root are now implemented on
> `feature/l3-ts-coordinator`; this is the integration seam over those
> lower-level domains. The L2 session event/result projection is wired as an
> explicit adapter in the same branch. This is an independent clean-break
> build; the Python3
> runtime remains the semantic reference and rollback path, not a dependency
> of the TS system.

## 1. Scope and authority

The TypeScript L3 layer owns logical Agent identity, decision orchestration,
bounded turn history, and lifecycle event projection. It does not own process
handles, terminals, PTYs, capability policy, GateChain decisions, or durable
kernel state.

| Boundary | Owner | Contract |
|---|---|---|
| L2 intent ingress | TS L2 / protocol v1 | `intentFromL2()` produces a normalized `AgentInput` |
| Agent coordination | TS L3 | `AgentRuntime`, bounded actions/history/events |
| Process/terminal/capability execution | Rust L1 | `RustKernelExecutionPort` and Rust gate/receipt |
| Python reference | Python3 | behavior oracle, rollback host, and gap-analysis source |

The three systems remain independent: TS never imports Python runtime modules,
Rust never imports TS or Python, and Python remains untouched by the new
runtime except through the existing versioned protocol.

## 2. Delivered slices (P0/P1)

- Versioned TS L3 agent contracts with separate identity, input, action,
  receipt, history, snapshot, and lifecycle-event values.
- `AgentRuntime` with per-identity busy exclusion, cancellation/fail-closed
  behavior, bounded UTF-8 input, action count, event data, and history.
- L2 adapter that rejects non-intent messages and session/identity mismatch.
- Protocol adapter that carries `operation`, JSON args, `ring`, `danger`, and
  `request_id` over the existing Rust host command boundary, then maps a
  Rust `result` envelope to a typed receipt. Rust echoes a supplied
  `request_id`; the TS adapter rejects a mismatched echo before admission.
- Defensive JSON copies and validation so provider-owned objects cannot mutate
  runtime state after admission. Provider callbacks receive a detached input
  copy, so identity and trace fields used for Rust requests cannot be
  rewritten after validation.
- Bounded provider adapter with an explicit deadline, propagated cancellation,
  detached context/history, input/history budget metadata, and payload-free
  latency telemetry. Provider timeout/cancellation cannot grant Rust authority
  or mutate the admitted input.
- Handler-free `ToolSpec` projection accepts Python-style registry JSON with
  deterministic ordering and bounded descriptions/parameters; `tool_call`
  actions resolve ring/danger from the registered projection and cross Rust as
  `tool.invoke`. Rust receipts fold into bounded `ToolResult` values without
  exposing handlers or executable objects.
- Read-only Memory/Prompt context is represented as identity-bound digest
  references with aggregate byte and count limits. Providers see no source
  text or storage handle; real memory/prompt loaders remain host adapters.
- Card lifecycle intents and scheduling requests are represented as bounded,
  identity-bound TypeScript values. Skill/TODO/evidence links remain IDs, and
  injected coordination ports return detached receipts without acquiring
  process, terminal, or capability authority.
- `l3/loop/` now provides one bounded FIFO AgentLoop per complete identity;
  `l3/cell/` lazily routes inputs to those loops. Queue backpressure,
  monotonic input sequencing, stop/drain transitions, and cancellation are
  explicit, while sibling identities remain independent.
- `l3/peer/` binds one attached L3A peer to the complete identity tuple and
  rejects conflicts, spoofed identities, stale routes, and detached peers.
  `l3/recovery/` retains a bounded, contiguous event window with cursor
  pagination and explicit resync signals; neither domain owns persistence or
  replays side effects.
- `l3/recovery/` now validates the Rust-owned execution checkpoint, correlates
  session/terminal/AgentLoop metadata by the complete identity, fences
  generation regressions, and returns a detached L3A resume vector. Peer
  handoff is preflighted against Rust and replay state before the binding moves.
- `l3/routing/` now provides a bounded L3B cross-Cell router. Registration,
  identity/trace validation, hop and metadata limits, detached route receipts,
  and fail-closed target rejection are implemented without taking persistence
  or process/terminal authority.
- `l3/coordinator/` now provides the public clean-break facade over L2 intent
  ingress, Cell/AgentLoop admission, and L3B forwarding. It owns no Cell
  handles outside its private registry, returns detached identity snapshots,
  and records payload-free bounded route counters/quantiles.
- `l3/adapters/l2-session-projection.ts` now projects lifecycle events and
  bounded intent outcomes into L2 protocol-v1 envelopes. Session sequence
  allocation remains an injected L2 authority; fanout to replay and frontend
  sinks copies event values before delivery.
- `l3/coordinator/l3-coordinator-host.ts` now composes the runtime, coordinator,
  replay ledger, L2 projection, and optional external observer in one
  injectable host boundary. Event fanout is ordered and detached per sink;
  durable outbox, cursor, transport, and Rust authority remain external.
- The host can now bind directly to the L2-owned
  `engine/l2-session-authority.ts`, which provides per-session sequence
  reservations, contiguous bounded replay, independent view cursors, and
  detached snapshots. Durable persistence and cross-process recovery remain
  explicit follow-up seams.
- `l3/governance/` now provides bounded sensitive detection, compression
  recursion/error-storm protection, review/edit-then-verify state, and a
  tamper-evident in-memory evidence projection. It is an optional host
  observer and never a second Rust execution or GateChain authority.

These slices are candidate-only. They are not the L2 production default, do not
replace Python AgentLoop/provider/tool execution, and do not satisfy the
Rust cutover gates by itself.

## 3. Prioritized construction plan

| Priority | Slice | Deliverable | Exit evidence | Status |
|---|---|---|---|---|
| P0 | Contract and ingress | freeze identity/input/action/receipt/event values | TS typecheck; malformed and cross-session inputs fail closed | ✅ complete |
| P0 | Rust execution seam | protocol-backed `RustKernelExecutionPort` | ring/danger/request-id mapping; denial and missing-result tests | ✅ complete |
| P1 | Provider adapter | provider-neutral decision port with timeout/budget metadata | detached context; deadline/cancel; telemetry; no direct process/tool imports | ✅ complete |
| P1 | Tool pipeline projection | data-only ToolSpec/ToolResult envelopes | Rust gate remains the only side-effect path; bounded result folding | ✅ complete |
| P1 | Memory and prompt context | read-only context ports and digest references | no Python object crossing; per-agent isolation and byte budgets | ✅ complete |
| P2 | Card coordination | bounded card lifecycle intents and detached receipts | card/skill/TODO/evidence links remain protocol values, not shared stores | ✅ first slice |
| P2 | Scheduler coordination | bounded priority/time/scope requests and detached queue receipts | queue ownership and fairness remain injected host policy | ✅ first slice |
| P2 | AgentLoop/Cell ingress | bounded per-identity FIFO queues and Cell routing | monotonic input sequence, cancellation, stop/drain, sibling isolation | ✅ first slice |
| P2 | Cell/L3A and recovery | session resume, event replay, Cell peer routing | identity and sequence vectors across TS/Rust | ✅ first slice |
| P2 | L3B cross-Cell routing | bounded Cell registry and direct validated `AgentInput` forwarding | detached receipts, identity/trace binding, hop/metadata bounds, fail-closed target errors | ✅ first slice |
| P2 | Rust checkpoint/session projection | metadata-only Rust session/terminal/AgentLoop projection, generation fence, peer handoff | identity correlation; no payload/process-handle leakage; failed preflight leaves route unchanged | ✅ first slice |
| P2 | L3 coordinator facade | L2 intent → registered Cell/AgentLoop → optional L3B route; detached snapshots and route evidence | coordinator-only boundary, no Python/process imports, bounded route stats, focused TS slices | ✅ first slice |
| P2 | L2 session event/result projection | project L3 lifecycle events and intent outcomes into protocol-v1 `event`/`result` envelopes; keep sequence allocation in L2 | validated envelopes, detached fanout, bounded payloads, runtime/coordinator sink tests | ✅ first slice |
| P2 | L3 host composition root | compose runtime, coordinator, replay projection, and L2 sink behind one injectable boundary | deterministic sink order, detached fanout isolation, injected replay retention, no transport/process ownership | ✅ first slice |
| P2 | L2 authoritative session boundary | own per-session output sequence, bounded replay, and per-view cursors below L3 | contiguous commit, non-destructive ack, detached replay, fail-closed reservations, host integration | ✅ first slice |
| P2 | Governance/evidence boundary | map sensitive/compression/review/verify/evidence semantics into bounded TS side channels | pattern/action bounds, breaker/reset semantics, review escalation, hash-chain verification, host observer isolation | ✅ first slice |
| P3 | Performance hardening | fixed-work TS/Rust slices and queue/lock telemetry | p95/p99, CPU/RSS, rejection/error counts under the shared schema | planned |
| P3 | Cutover decision | explicit opt-in → reversal matrix → default switch | G1–G6 gates green; Python host retirement only after evidence | planned |

## 4. Invariants and optimization rules

1. Every side effect crosses the Rust port; an unbound or rejected port fails
   closed.
2. Agent identities are isolated by the full
   `(agent_id, cell_id, session_id, terminal_id)` tuple.
3. Input, action, event, receipt, and history payloads are bounded in UTF-8
   bytes or count; no unbounded provider output is retained.
4. Rust receipts must match request and trace identifiers; a missing or
   malformed result is an error, not an implicit success.
5. Python optimizations are limited to the reference host's measurable wire
   path (byte counting, decode-before-cap, one flush per response set); they
   must not become hidden TS/Rust authority.
6. Benchmarks are evidence only. No worker count, queue strategy, or host
   implementation becomes production policy without repeatable fixed-work
   results.

## 5. Verification and archive rules

Each slice runs as an independent test domain. At minimum, record:

- TS `tsc --noEmit` and focused Vitest leaves;
- provider deadline/cancellation tests must run independently from Rust
  process/terminal tests; telemetry assertions contain counts/timing only;
- Rust focused protocol/AgentLoop/host tests;
- Python protocol reference tests for any wire-path change;
- `git diff --check`, naming/layer-boundary checks, and attribution before
  commit.

When a slice closes, move its detailed construction document to the design
archive according to `docs/workflow/README.md`; keep this roadmap directional
and update its status rather than appending a historical implementation log.
