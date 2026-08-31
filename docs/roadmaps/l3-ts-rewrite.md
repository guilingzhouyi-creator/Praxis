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

> Status: P0 contract/ingress and the first P1 provider-boundary slice are
> implemented on `feature/l1-rust-host-bootstrap` (TS L2 intent → detached
> provider context → TS L3 coordinator → Rust protocol execution port). This
> is an independent clean-break build; the Python3 runtime remains the
> semantic reference and rollback path, not a dependency of the TS system.

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

These slices are candidate-only. They are not the L2 production default, do not
replace Python AgentLoop/provider/tool execution, and do not satisfy the
Rust cutover gates by itself.

## 3. Prioritized construction plan

| Priority | Slice | Deliverable | Exit evidence | Status |
|---|---|---|---|---|
| P0 | Contract and ingress | freeze identity/input/action/receipt/event values | TS typecheck; malformed and cross-session inputs fail closed | ✅ complete |
| P0 | Rust execution seam | protocol-backed `RustKernelExecutionPort` | ring/danger/request-id mapping; denial and missing-result tests | ✅ complete |
| P1 | Provider adapter | provider-neutral decision port with timeout/budget metadata | detached context; deadline/cancel; telemetry; no direct process/tool imports | ✅ complete |
| P1 | Tool pipeline projection | data-only ToolSpec/ToolResult envelopes | Rust gate remains the only side-effect path; bounded result folding | next |
| P1 | Memory and prompt context | read-only context ports and digest references | no Python object crossing; per-agent isolation and byte budgets | planned |
| P2 | Card and scheduler coordination | card lifecycle intents and bounded scheduling requests | card/skill/TODO links remain protocol values, not shared stores | planned |
| P2 | Cell/L3A and recovery | session resume, event replay, Cell peer routing | identity and sequence vectors across TS/Rust | planned |
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
