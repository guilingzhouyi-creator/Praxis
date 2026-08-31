---
pointer: DESIGN-2026-08-31-111
archive_number: DESIGN-2026-永久-111
fonds: DESIGN
year: 2026
retention: 永久
title: "TS L3A Peer Routing and Event Replay Slice"
author: Codex
formation_date: 2026-08-31
carrier: md
classification: 内部
pages: 74
archivist: L3
reviewer: L3
archive_date: 2026-08-31
source: design
keywords: "[typescript, l3a, peer, replay, recovery]"
abstract: "Define the bounded TypeScript L3A peer routing and event replay domains for clean-break session resume."
construction: in_progress
---

# TS L3A Peer Routing and Event Replay Slice

## Scope

This construction slice extends the clean-break TypeScript L3 coordinator
with two independent domains:

- `src/l3/peer/` binds one logical L3A peer to one complete Agent identity
  and routes only identity-matching inputs to an `AgentCell`.
- `src/l3/recovery/` provides an in-memory, bounded lifecycle-event replay
  window for cursor-based resume projections.

The domains are value and coordination boundaries only. Rust L1 remains the
authority for durable session, terminal, process, capability, and hard-policy
state. The TypeScript ledger never writes checkpoints or replays side effects;
the Python runtime remains the semantic reference and rollback host.

## Contract

`L3APeerRouter` enforces one attached peer per full
`(agentId, cellId, sessionId, terminalId)` identity, rejects identity
spoofing, preserves detached peer tombstones, and delegates admitted turns to
the existing bounded `AgentCell`.

`EventReplayLedger` implements `AgentEventSink`, requires contiguous event
sequences per identity, bounds retained events, returns deterministic
cursor-based pages, and marks a response `requiresResync` when the requested
cursor predates the retained window. Responses and snapshots are detached
copies, so callers cannot mutate the ledger.

## Delivered evidence

- `src/l3/peer/l3a-peer-router.ts`
- `src/l3/recovery/event-replay-ledger.ts`
- `src/l3/l3-agent-entry.ts` exports both domains.
- `tests/l3-peer-recovery.test.ts` covers cursor pagination, truncation,
  sequence gaps, payload isolation, peer conflicts, stale routes, draining,
  and runtime-event integration.
- `L3_MAX_REPLAY_EVENTS` provides the bounded replay default.

## Remaining work

This document remains open. The next slices are:

1. Rust checkpoint/session projection joined to the TS peer route without
   granting TS persistence authority.
2. L3A peer handoff and resume vectors across L2 protocol cursors and Rust
   execution generations.
3. Fixed-work queue/replay performance evidence, including p95/p99 latency,
   memory ceiling, and resync frequency.

Close this plan only when those slices have independent evidence and the
roadmap exit criteria are green; then move it through
`docs/design/_outgoing/` for archival ingestion.
