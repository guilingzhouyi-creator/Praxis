---
pointer: DESIGN-2026-08-31-114
archive_number: DESIGN-2026-永久-114
fonds: DESIGN
year: 2026
retention: 永久
title: "TS L3 Coordinator Facade Slice"
author: Codex
formation_date: 2026-08-31
carrier: md
classification: 内部
pages: 72
archivist: L3
reviewer: L3
archive_date: 2026-08-31
source: design
keywords: "[typescript, l3, coordinator, agentloop, rust]"
abstract: "Define the clean-break TypeScript L3 coordinator facade joining L2 intent ingress, Cell admission, and bounded cross-Cell route evidence."
series: active
date: 2026-08-31
status: active
construction: in_progress
---

# TS L3 Coordinator Facade Slice

## Scope

This slice adds the public TypeScript L3 facade over the already-bounded
AgentRuntime, AgentCell, AgentLoop, and L3B CrossCellRouter domains. It is a
clean-break construction: Python remains a semantic reference and rollback
host, while Rust remains the only process, terminal, capability, and
hard-constraint authority.

The facade accepts a protocol-v1 `Message`, normalizes intent messages through
`intentFromL2()`, and admits the resulting `AgentInput` to the registered Cell.
It can also forward a validated cross-Cell request and expose detached
registration, identity snapshot, and route-statistics values.

## Contract and invariants

- A coordinator owns one `AgentRuntime` and constructs registered Cells around
  that runtime; callers never receive the private Cell map or AgentLoop
  handles.
- Local submission is admitted only when `input.identity.cellId` is registered.
  L2 command/control/event messages are rejected by the existing intent
  adapter before reaching L3.
- `submitIntent()` copies the caller identity and `submit()` copies the
  normalized input before Cell admission, preserving the identity boundary.
- Snapshot values join the Cell loop view with the runtime view and are
  detached; no provider, Python object, process handle, terminal handle, or
  persistence handle crosses this facade.
- Route metrics retain only bounded counters and recent latency samples.
  `validationErrors` is a subset of rejected coordinator route attempts that
  fail before target Cell admission; payload and identity values are never
  retained.
- `drain()` stops admission through the existing Cell semantics but keeps
  registration summaries available for post-drain inspection.

## Implemented files

- `systems/typescript-shell-engine/src/l3/coordinator/l3-coordinator.ts`
  - coordinator construction, Cell registration, L2 intent ingress, local
    submission, cross-Cell route forwarding, detached snapshots, bounded
    route statistics, stop, and drain;
- `systems/typescript-shell-engine/src/l3/l3-agent-entry.ts`
  - public facade export;
- `systems/typescript-shell-engine/tests/l3-coordinator.test.ts`
  - ingress, registration, identity detachment, route evidence, rejection,
    drain, and idempotent registration coverage;
- `docs/architecture/l3-module-map.md`
  - coordinator ownership and module inventory;
- `docs/roadmaps/l3-ts-rewrite.md`
  - P2 coordinator-facade status and next integration seam.
- `systems/typescript-shell-engine/src/l3/adapters/l2-session-projection.ts`
  - L2 protocol-v1 output projection and injected sequence/fanout boundary;
  coordinator integration publishes successful and failed intent outcomes.

## Verification slice

The independent verification domain is:

```bash
/home/guiling/.local/node/bin/node /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/typescript/bin/tsc --noEmit -p systems/typescript-shell-engine/tsconfig.json --typeRoots /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/@types
/home/guiling/.local/node/bin/node /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/vitest/vitest.mjs run tests/l3-coordinator.test.ts tests/l3-agent-loop-cell.test.ts tests/l3-cross-cell-routing.test.ts --pool=threads --maxWorkers=3
```

Observed result: TypeScript typecheck clean; the coordinator-focused subset
(3 test files, 17 tests) passes. The combined L3A recovery/projection slice
(4 test files, 26 tests) is also green.
This slice does not claim Python or Rust full-suite coverage, durable route
handoff, provider cutover, or production-default activation.

## Remaining work

1. Add a host-facing L2 session adapter that owns coordinator construction
   and event-sink composition without making the TS L3 facade a transport
   implementation.
2. Reconcile coordinator route metrics with the L3B router's independent
   telemetry slice when that branch is merged, preserving one shared metric
   schema and avoiding double counting.
3. Add fixed-work L3/Rust end-to-end evidence, CPU/RSS ceilings, and cutover
   reversal tests before any production-default switch.
4. Keep this construction document `in_progress` until those external
   contracts have independent evidence; archive it through
   `docs/design/_outgoing/` only when closed.
