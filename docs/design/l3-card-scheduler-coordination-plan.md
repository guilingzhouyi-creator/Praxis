---
pointer: DESIGN-2026-08-31-109
archive_number: DESIGN-2026-永久-109
fonds: DESIGN
year: 2026
retention: 永久
title: "TS L3 Card and Scheduler Coordination Slice"
author: Codex
formation_date: 2026-08-31
carrier: md
classification: 内部
pages: 60
archivist: L3
reviewer: L3
archive_date: 2026-08-31
source: design
keywords: [typescript, l3, card, scheduler, coordination]
abstract: "Define the first clean-break TypeScript L3 Card and Scheduler data-only coordination seams."
series: active
date: 2026-08-31
status: active
construction: in_progress
---

# TS L3 Card and Scheduler Coordination Slice

## Scope

This construction slice adds two independent TypeScript L3 domains:

- `l3/card/` validates lifecycle intents and preserves Skill/TODO/evidence
  links as bounded identifiers.
- `l3/scheduler/` validates priority, time, cost, queue, and scope requests.

Both domains bind requests to the full Agent identity and trace identifier.
They return detached receipts through injected TypeScript ports. They do not
open stores, own queue fairness, execute tools, mount terminals, or bypass the
Rust execution authority.

## Delivered

- Discriminated `card_intent` and `schedule_request` actions.
- Count and UTF-8 byte bounds for titles, links, IDs, metadata, and payloads.
- Deadline ordering and priority/cost validation.
- Receipt correlation and acceptance/status invariants.
- `AgentRuntime` integration with bounded lifecycle events and result arrays.
- Independent Vitest coverage in `tests/l3-card-scheduler.test.ts`.

## Remaining work

This document remains open. The next L3 slices are:

1. Cell/L3A peer routing and session-resume data contracts.
2. Event replay/recovery projections with identity and sequence vectors.
3. Host adapters for real card/scheduler stores, with no Python object crossing.
4. Performance evidence for coordination queue pressure and receipt latency.

When all four items have independent evidence and the roadmap exit criteria
are met, close this document by setting `construction: closed` and moving it
through `docs/design/_outgoing/` so the archive gate can ingest it.
