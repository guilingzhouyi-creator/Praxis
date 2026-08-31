---
pointer: DESIGN-2026-08-31-112
archive_number: DESIGN-2026-永久-112
fonds: DESIGN
year: 2026
retention: 永久
title: "TS L3A Rust-Fenced Session Resume Slice"
author: Codex
formation_date: 2026-08-31
carrier: md
classification: 内部
pages: 105
archivist: L3
reviewer: L3
archive_date: 2026-08-31
source: design
keywords: "[typescript, l3a, recovery, rust, resume]"
abstract: "Define the Rust-fenced TypeScript L3A session resume projection, generation fence, replay join, and atomic peer handoff."
series: active
date: 2026-08-31
status: active
construction: in_progress
---

# TS L3A Rust-Fenced Session Resume Slice

## Scope

This construction slice closes the first TypeScript recovery seam between the
Rust L1 execution authority, the L3A peer router, and the bounded TypeScript
event replay ledger. It is a clean-break projection: TypeScript receives
detached JSON-shaped checkpoint metadata and never acquires Rust persistence,
process, terminal, or message-body ownership.

The new recovery domain lives under
`systems/typescript-shell-engine/src/l3/recovery/`. The folder is a
TypeScript L3 coordination domain, not a shared runtime or compatibility
layer. It may only consume the injected `RustExecutionProjectionPort`,
`EventReplayLedger`, and `L3APeerRouter` contracts.

## Contract and authority

Rust remains the only authority that reads durable execution checkpoints and
owns process/terminal state. The projection adapter accepts the versioned
execution-store document, validates bounded session, terminal, and AgentLoop
metadata, and exposes only:

- session identity, lifecycle, cursors, clean-shutdown state, and retained
  message count;
- terminal identity, lifecycle, queue depths, drop counters, and a
  `processBound` flag instead of a process handle;
- AgentLoop identity, lifecycle, command cursor, counters, and lock-wait
  telemetry.

Session message bodies are validated for shape but are not copied into the
TypeScript projection. Process IDs are reduced to the boolean `processBound`.
Complete `(agentId, cellId, sessionId, terminalId)` correlation is mandatory;
missing, duplicated, or cross-wired entities fail closed.

## Resume and handoff behavior

`L3ASessionResumeCoordinator` joins three detached views:

1. Rust checkpoint metadata and its monotonic `generation`;
2. the bounded, contiguous replay window and its event cursor;
3. the identity-safe `L3APeerRouter` binding.

Resume enforces attached-peer identity, optional optimistic generation
matching, and a per-identity generation fence. An unclean checkpoint or
failed Rust/AgentLoop/terminal state returns `requires_reactivation`; it does
not silently resume execution. Peer handoff performs Rust and replay
preflight before moving the route, while the source peer remains a detached
tombstone. A failed preflight leaves the source route attached and the target
absent.

The resulting `L3AResumeVector` is a detached L2-consumable value containing
continuity cursors, lifecycle summaries, replay events, and recovery status.
It contains no checkpoint payloads, process handles, storage references, or
mutable router state.

## Delivered evidence

- `src/l3/recovery/rust-execution-projection.ts`
  - version, identity, lifecycle, count, and safe-integer validation;
  - metadata-only projection and complete-identity correlation;
  - bounded entity arrays via `L3_MAX_RUST_PROJECTION_ENTITIES`.
- `src/l3/recovery/l3a-session-resume.ts`
  - generation fence, cancellation, expected-generation checks, and
    reactivation status;
  - atomic peer handoff only after asynchronous preflight succeeds.
- `src/l3/peer/l3a-peer-router.ts`
  - identity-preserving handoff with detached source tombstones.
- `tests/l3-session-resume.test.ts`
  - projection sanitization and malformed/oversized inputs;
  - clean and unclean resume vectors;
  - generation regression fencing;
  - missing and cross-wired identity rejection;
  - successful handoff and failed-preflight route preservation.

## Verification slice

The independent TypeScript slice is verified with:

```bash
npm run typecheck --prefix systems/typescript-shell-engine
npx vitest run systems/typescript-shell-engine/tests/l3-session-resume.test.ts
npx vitest run systems/typescript-shell-engine/tests/l3-*.test.ts
```

These checks do not claim Python full-suite or Rust full-suite coverage. The
Rust checkpoint reader and persistence implementation remain outside this
candidate slice and must be validated by their own Rust domain tests before
cutover.

## Remaining work

1. Add a Rust host adapter that emits the versioned checkpoint projection over
   the existing protocol without leaking durable payloads.
2. Add an L2 session adapter that consumes `L3AResumeVector` and maps replay
   cursors to the protocol v1 wire contract.
3. Record fixed-work p95/p99 resume and handoff latency, memory ceilings,
   rejected recovery counts, and replay resync frequency under the shared
   quantitative schema.
4. Keep the Python runtime as semantic reference and rollback host until the
   Rust/TS cutover gates are independently green.

Close this document only after the host adapter, L2 wire mapping, and
performance evidence have independent tests; then move it through
`docs/design/_outgoing/` for archival ingestion.
