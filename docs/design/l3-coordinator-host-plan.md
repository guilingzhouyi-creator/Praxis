---
pointer: DESIGN-2026-08-31-116
archive_number: DESIGN-2026-永久-116
fonds: DESIGN
year: 2026
retention: 永久
title: "TS L3 Coordinator Host Composition Slice"
author: Codex
formation_date: 2026-08-31
carrier: md
classification: 内部
pages: 58
archivist: L3
reviewer: L3
archive_date: 2026-08-31
source: design
keywords: "[typescript, l3, host, replay, l2, rust]"
abstract: "Compose the clean-break TypeScript L3 runtime, bounded replay ledger, and L2 session projection behind one injectable host boundary."
series: active
date: 2026-08-31
status: active
construction: in_progress
---

# TS L3 Coordinator Host Composition Slice

## Scope

This slice adds the host-facing composition root for the clean-break
TypeScript L3 coordinator. It wires one `AgentRuntime` to a bounded
`EventReplayLedger`, an `L2SessionProjection`, and an optional external
`AgentEventSink` without turning L3 into a transport, persistence, process, or
terminal implementation.

Rust remains the sole authority for processes, terminals, capabilities, and
hard constraints. L2 remains the authority for session delivery and sequence
allocation. The replay ledger is an in-memory recovery projection only.
Python is not imported and remains a semantic reference/rollback host.

## Contract and invariants

- `createL3CoordinatorHost()` constructs exactly one runtime and coordinator
  over the same runtime instance.
- Event delivery is deterministic: replay first, L2 projection second, then
  the optional external observer.
- `fanoutAgentEventSinks()` gives every sink a detached event value, so a
  diagnostic observer cannot mutate replay or frontend projections.
- A caller may inject an existing replay ledger; host construction preserves
  that ledger and its configured retention window.
- The L2 sink and sequence authority are injected. The host does not create
  durable outbox, cursor, transport, process, terminal, or provider state.
- Runtime options remain data-only seams. No Python module, Rust
  implementation, Node process API, PTY, or tool handler crosses the host
  boundary.

## Implemented files

- `systems/typescript-shell-engine/src/l3/coordinator/l3-coordinator-host.ts`
  - composition root, injected replay support, deterministic event fanout, and
    detached host surface;
- `systems/typescript-shell-engine/src/l3/l3-agent-entry.ts`
  - public host export;
- `systems/typescript-shell-engine/tests/l3-coordinator-host.test.ts`
  - event ordering, replay/L2 isolation from observer mutation, and injected
    replay retention coverage;
- `docs/architecture/l3-module-map.md`
  - host composition ownership row;
- `docs/roadmaps/l3-ts-rewrite.md`
  - P2 host-composition status and P3 follow-up boundary;
- `docs/design/l3-coordinator-plan.md`
  - host adapter no longer listed as an outstanding implementation item;
- `docs/design/l3-l2-session-projection-plan.md`
  - host composition no longer listed as an outstanding implementation item.

## Verification slice

The independent verification domain is:

```bash
/home/guiling/.nvm/versions/node/v24.19.0/bin/node /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/typescript/bin/tsc --noEmit -p systems/typescript-shell-engine/tsconfig.json --typeRoots /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/@types
/home/guiling/.nvm/versions/node/v24.19.0/bin/node /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/vitest/vitest.mjs run --pool=threads --maxWorkers=4 tests/l3-coordinator-host.test.ts tests/l3-coordinator.test.ts tests/l3-l2-session-projection.test.ts tests/l3-agent-runtime.test.ts
/home/guiling/.nvm/versions/node/v24.19.0/bin/node /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/vitest/vitest.mjs run --pool=threads --maxWorkers=4 tests/l3-agent-loop-cell.test.ts tests/l3-cross-cell-routing.test.ts tests/l3-peer-recovery.test.ts tests/l3-session-resume.test.ts
```

Observed result: TypeScript typecheck clean; the host/coordinator/projection
slice passes 4 files and 28 tests; the AgentLoop/Cell/routing/recovery slice
passes 4 files and 24 tests. This is slice evidence only and does not claim
durable L2 outbox integration, Rust process coverage, Python full-suite
coverage, or production cutover.

## Remaining work

1. Replace the in-memory sequence/replay pair with the authoritative L2
   session outbox and cursor ports in a separate integration slice.
2. Reconcile coordinator route evidence with the L3B route-hardening telemetry
   branch without double counting.
3. Add fixed-work TS/Rust process evidence, CPU/RSS ceilings, and reversal
   tests before enabling a production-default path.
4. Keep this construction document `in_progress` until those external
   contracts have independent evidence; archive it through
   `docs/design/_outgoing/` only when closed.
