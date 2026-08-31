---
pointer: DESIGN-2026-08-31-113
archive_number: DESIGN-2026-永久-113
fonds: DESIGN
year: 2026
retention: 永久
title: "TS L3B Cross-Cell Routing Slice"
author: Codex
formation_date: 2026-08-31
carrier: md
classification: 内部
pages: 94
archivist: L3
reviewer: L3
archive_date: 2026-08-31
source: design
keywords: "[typescript, l3b, cross-cell, routing, rust]"
abstract: "Define the bounded TypeScript L3B cross-Cell routing registry and detached handoff receipt for the clean-break rewrite."
series: active
date: 2026-08-31
status: active
construction: in_progress
---

# TS L3B Cross-Cell Routing Slice

## Scope

This slice registers the new `systems/typescript-shell-engine/src/l3/routing/`
coordination folder and adds a bounded cross-Cell forwarding boundary. It is a
clean-break TypeScript domain: Python remains the semantic reference, while
Rust remains the only process, terminal, capability, and hard-constraint
authority.

The router forwards an already-normalized `AgentInput` to a target
`AgentCell`. It does not load persistence, inspect Python objects, open a
terminal, or acquire a Rust process handle.

## Contract and invariants

- Cell registration is O(1) by `cellId`, bounded by
  `L3_MAX_REGISTERED_CELLS`, and repeating the same Cell instance is
  idempotent.
- Source and target identities must differ, must belong to different
  registered Cells, and the input identity/trace must match the target route.
- Route identifiers, hop count, and optional JSON metadata have explicit
  UTF-8/count limits; malformed, cyclic, non-finite, or oversized metadata
  fails closed.
- Each admitted forwarding increments the hop count and rejects routes that
  reach `L3_MAX_CROSS_CELL_HOPS`.
- Public registration and route results are detached values. The router never
  exposes its `AgentCell` map or an `AgentLoop` handle.
- Target admission failures become a detached `rejected` receipt; they do not
  become uncaught runtime exceptions.

## Implemented files

- `src/l3/routing/cross-cell-router.ts`
  - bounded registration, deterministic summaries, validation, forwarding,
    detached receipts, and drain support;
- `src/l3/runtime/limits.ts`
  - Cell, hop, route-id, and metadata bounds;
- `src/l3/contracts/agent-contracts.ts`
  - route-specific fail-closed error codes;
- `src/l3/l3-agent-entry.ts`
  - public L3 entry export;
- `tests/l3-cross-cell-routing.test.ts`
  - registration idempotence, delivery, identity/trace/hop checks, target
    rejection, and registration-bound behavior.

## Verification slice

The independent verification domain is:

```bash
/home/guiling/.local/node/bin/node systems/typescript-shell-engine/node_modules/typescript/bin/tsc --noEmit -p systems/typescript-shell-engine/tsconfig.json
/home/guiling/.local/node/bin/node node_modules/vitest/vitest.mjs run tests/l3-cross-cell-routing.test.ts
```

The focused L3 suite must also remain green. These checks do not claim
Python or Rust full-suite coverage, durable handoff, or cross-Cell HTN/card
execution.

## Remaining work

1. Add a Rust host adapter and L2 wire mapping when the cross-Cell route needs
   to cross a process boundary.
2. Add durable handoff and real HTN/card coordination only after the host
   authority and persistence contracts are frozen.
3. Record fixed-work p95/p99 route latency, queue/lock telemetry, memory
   ceilings, and rejected-route counts under the shared quantitative schema.
4. Keep this construction document `in_progress` until those external
   contracts and evidence have independent tests; archive it through
   `docs/design/_outgoing/` only when closed.
