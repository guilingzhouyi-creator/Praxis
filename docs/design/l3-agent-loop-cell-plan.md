---
pointer: DESIGN-2026-08-31-110
archive_number: DESIGN-2026-永久-110
fonds: DESIGN
year: 2026
retention: 永久
title: "TS L3 AgentLoop and Cell Coordination Slice"
author: Codex
formation_date: 2026-08-31
carrier: md
classification: 内部
pages: 79
archivist: L3
reviewer: L3
archive_date: 2026-08-31
source: design
keywords: "[typescript, l3, agentloop, cell, coordination]"
abstract: "Define the bounded TypeScript L3 AgentLoop and Cell coordination domains for the clean-break rewrite."
construction: in_progress
---

# TS L3 AgentLoop and Cell Coordination Slice

## Scope

This construction slice registers two TypeScript L3 domains for the
clean-break rewrite:

- `src/l3/loop/` owns one bounded FIFO AgentLoop per complete identity.
- `src/l3/cell/` routes inputs to identity-bound loops within one logical Cell.

The domains are coordination-only. Rust L1 remains the sole authority for
processes, terminals, capabilities, GateChain decisions, and hard constraints.
Python remains the semantic reference and rollback host. No implementation
imports a Python object, Rust implementation, PTY, process handle, or durable
store.

## Contract

The routing key is the complete tuple
`(agentId, cellId, sessionId, terminalId)`. A loop:

- accepts only identity-matching inputs with monotonically increasing
  `inputSeq` values;
- bounds pending admission with `L3_MAX_PENDING_INPUTS`;
- serializes one identity while allowing sibling identities to progress
  independently;
- propagates caller and loop-stop cancellation to `AgentRuntime`;
- exposes detached snapshots for queue depth, lifecycle state, counters, and
  the last failure.

`AgentCell` lazily creates loops, rejects malformed identities, preserves
per-identity FIFO ordering, and drains all admitted work without exposing
runtime handles.

## Delivered evidence

- `src/l3/loop/agent-loop-queue.ts`
- `src/l3/cell/agent-cell.ts`
- `src/l3/l3-agent-entry.ts` exports both domains.
- `tests/l3-agent-loop-cell.test.ts` covers FIFO sequencing, queue
  backpressure, cancellation, identity isolation, and drain/stop behavior.
- `AgentRuntime` re-checks cancellation after asynchronous event/context
  boundaries before provider admission.

## Remaining work

This document remains open. The next slices are:

1. L3A peer routing and session-resume data contracts.
2. Event replay/recovery projections with identity and sequence vectors.
3. Host adapters for durable Cell/AgentLoop state, without Python object
   crossing or TS-owned persistence authority.
4. Fixed-work performance evidence for queue pressure, cancellation latency,
   and cross-identity concurrency.

Close this plan only after those slices have independent evidence and the
roadmap exit criteria are green; then move it through
`docs/design/_outgoing/` for archival ingestion.
