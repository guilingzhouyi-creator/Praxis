---
pointer: DESIGN-2026-08-31-117
archive_number: DESIGN-2026-永久-117
fonds: DESIGN
year: 2026
retention: 永久
title: "TS L2 Authoritative Session Boundary Slice"
author: Codex
formation_date: 2026-08-31
carrier: md
classification: 内部
pages: 74
archivist: L2
reviewer: L3
archive_date: 2026-08-31
source: design
keywords: "[typescript, l2, session, outbox, cursor, l3]"
abstract: "Provide a bounded TypeScript L2 session authority for output sequencing, replay windows, and per-frontend cursors without taking L3 or Rust authority."
series: active
date: 2026-08-31
status: active
construction: in_progress
---

# TS L2 Authoritative Session Boundary Slice

## Scope

This slice adds an explicit TypeScript L2 host authority for protocol-v1
output messages. It owns per-session sequence reservations, a bounded replay
window, and per-frontend acknowledgement cursors. It is separate from
`SessionManager` and `SessionMultiplexer`, which remain client-side mirrors.

The authority is an in-memory host/reference implementation. It does not
claim durable persistence, transport ownership, AgentLoop state, provider
state, process/terminal control, or Rust policy. The L3 coordinator host may
inject it as both the sequence port and message sink.

## Contract and invariants

- Session output sequences are reserved per session and never process-global.
- Concurrent projections may reserve sequences out of order, but messages are
  visible to replay only after the contiguous prefix is committed.
- A reserved-but-unpublished sequence is retained as bounded `pendingMessages`
  evidence; later messages cannot silently skip it.
- Each frontend view has an independent monotonic cursor. Ack is
  non-destructive and never deletes another view's replay window.
- Replay and snapshot results are detached copies; callers cannot mutate
  authority-owned envelopes.
- Session count, outbox length, identifier shape, envelope validity, sequence
  reservations, and view attachment are fail-closed and bounded.
- The authority is injected below L3 projection; L3 does not import or own its
  internal session map.

## Implemented files

- `systems/typescript-shell-engine/src/engine/l2-session-authority.ts`
  - bounded sequence reservation, contiguous commit, replay, per-view cursor,
    detached snapshots, and fail-closed errors;
- `systems/typescript-shell-engine/src/l3/adapters/l2-session-projection.ts`
  - consumes the L2-owned sequence/sink interfaces without importing upward
    into L3;
- `systems/typescript-shell-engine/src/l3/coordinator/l3-coordinator-host.ts`
  - accepts an injected `L2SessionAuthority` as the host's projection source;
- `systems/typescript-shell-engine/tests/l2-session-authority.test.ts`
  - ordering, bounded replay, detached copies, multi-view ack, reattach,
    conflict, stale, and session-limit evidence;
- `systems/typescript-shell-engine/tests/l3-coordinator-host.test.ts`
  - end-to-end host projection into the L2 authority;
- `docs/architecture/l2-shell-engine.md`
  - L2 authority boundary and module inventory;
- `docs/roadmaps/l2-multifrontend-session-layer.md`
  - authority status and remaining durable-host work;
- `docs/roadmaps/l3-ts-rewrite.md`
  - L2 authority integration status;
- `docs/design/l3-coordinator-host-plan.md`
  - authority integration replaces the in-memory-only host follow-up.

## Verification slice

The independent verification domain is:

```bash
/home/guiling/.nvm/versions/node/v24.19.0/bin/node /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/typescript/bin/tsc --noEmit -p systems/typescript-shell-engine/tsconfig.json --typeRoots /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/@types
/home/guiling/.nvm/versions/node/v24.19.0/bin/node /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/vitest/vitest.mjs run --pool=threads --maxWorkers=4 tests/l2-session-authority.test.ts tests/l3-coordinator-host.test.ts tests/l3-l2-session-projection.test.ts tests/l3-coordinator.test.ts
```

Observed result: TypeScript typecheck clean; 4 focused files and 22 tests
pass. This does not claim durable persistence, multi-process recovery,
Rust/Python full-suite parity, or production cutover.

## Remaining work

1. Replace the in-memory record with an injected durable L2 outbox/cursor
   implementation while preserving this interface and its replay semantics.
2. Add protocol-host attach/recovery integration and multi-process crash/restart
   evidence.
3. Add fixed-work sequence/replay throughput, CPU/RSS, and contention baselines.
4. Keep this construction document `in_progress` until durable and
   cross-process evidence is independently verified.
