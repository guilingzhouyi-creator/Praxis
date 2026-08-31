---
pointer: DESIGN-2026-08-31-115
archive_number: DESIGN-2026-永久-115
fonds: DESIGN
year: 2026
retention: 永久
title: "TS L3 to L2 Session Projection Slice"
author: Codex
formation_date: 2026-08-31
carrier: md
classification: 内部
pages: 86
archivist: L3
reviewer: L3
archive_date: 2026-08-31
source: design
keywords: "[typescript, l3, l2, session, projection, rust]"
abstract: "Define the detached TypeScript L3 lifecycle/result projection into the L2 protocol-v1 session data boundary."
series: active
date: 2026-08-31
status: active
construction: in_progress
---

# TS L3 to L2 Session Projection Slice

## Scope

This slice closes the first explicit output cable between the clean-break
TypeScript L3 coordinator and the L2 multi-frontend session data layer. It
does not turn L3 into a transport implementation: L2 owns session sequence
authority, replay/outbox policy, and frontend delivery, while the projection
only translates detached lifecycle events and bounded intent outcomes.

Rust remains the only process, terminal, capability, and hard-constraint
authority. Python remains the semantic reference and audit-chain source. No
Python object, provider callback, process handle, terminal handle, or durable
store is imported by this adapter.

## Contract and invariants

- `L2SessionProjection` implements the existing `AgentEventSink` contract and
  emits protocol-v1 `event` messages with the complete Agent identity nested
  under a detached metadata object.
- Successful and failed intent outcomes are explicit `result` envelopes.
  They carry bounded summaries and counts, not raw Rust receipts, tool
  payloads, provider output objects, or execution handles.
- Session output sequence allocation is injected through
  `L2SessionSequencePort`; the provided `SessionSequenceAllocator` is a
  bounded in-memory test/host implementation, not a replacement for durable
  L2 session authority.
- `fanoutAgentEventSinks()` delivers cloned event values in registration order,
  so a diagnostic or replay sink cannot mutate the value observed by another
  sink.
- Projected payloads are validated and bounded before the optional L2 message
  sink receives them. Sink failures remain visible to the caller and cannot
  silently grant Rust authority.
- The coordinator can optionally publish intent result/failure envelopes after
  Cell admission while preserving the original `AgentRuntimeError`.

## Implemented files

- `systems/typescript-shell-engine/src/l3/adapters/l2-session-projection.ts`
  - protocol-v1 event/result conversion, bounded session sequence allocator,
    and detached event-sink fanout;
- `systems/typescript-shell-engine/src/l3/coordinator/l3-coordinator.ts`
  - optional result/failure projection for `submitIntent()`;
- `systems/typescript-shell-engine/src/l3/l3-agent-entry.ts`
  - public adapter export;
- `systems/typescript-shell-engine/src/l3/coordinator/l3-coordinator-host.ts`
  - host composition root that wires replay, projection, and runtime event
    fanout;
- `systems/typescript-shell-engine/tests/l3-l2-session-projection.test.ts`
  - allocator bounds, envelope validation, alias isolation, fanout ordering,
    runtime event integration, and result/failure projections;
- `systems/typescript-shell-engine/tests/l3-coordinator.test.ts`
  - coordinator-to-L2 success/failure sink coverage;
- `docs/architecture/l3-module-map.md`
  - L2/L3 adapter ownership row;
- `docs/roadmaps/l3-ts-rewrite.md`
  - P2 session projection status.

## Verification slice

The independent verification domain is:

```bash
/home/guiling/.local/node/bin/node /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/typescript/bin/tsc --noEmit -p systems/typescript-shell-engine/tsconfig.json --typeRoots /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/@types
/home/guiling/.local/node/bin/node /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/vitest/vitest.mjs run tests/l3-l2-session-projection.test.ts tests/l3-coordinator.test.ts tests/l3-peer-recovery.test.ts tests/l3-session-resume.test.ts --pool=threads --maxWorkers=4
```

Observed result: TypeScript typecheck clean; 4 test files and 26 tests pass.
The broader L3 slice remains independently verified; this does not claim
durable L2 outbox integration, Python/Rust full-suite coverage, or cutover.

## Remaining work

1. Replace the in-memory sequence/replay pair with a host adapter over the
   authoritative session outbox and replay cursors.
2. Reconcile the coordinator-level route evidence with the independent L3B
   router telemetry slice without double counting after that branch merges.
3. Add fixed-work TS/Rust process evidence, CPU/RSS ceilings, and reversal
   tests before enabling any production-default path.
4. Keep this document `in_progress` until the host adapter and external
   evidence are closed; archive it through `docs/design/_outgoing/` only when
   implementation and verification are complete.
