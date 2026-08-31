---
pointer: DESIGN-2026-08-31-118
archive_number: DESIGN-2026-永久-118
fonds: DESIGN
year: 2026
retention: 永久
title: "TS L3 Governance and Evidence Boundary Slice"
author: Codex
formation_date: 2026-08-31
carrier: md
classification: 内部
pages: 96
archivist: L3
reviewer: L3
archive_date: 2026-08-31
source: design
keywords: "[typescript, l3, governance, evidence, sensitive, compression]"
abstract: "Map Python L3 governance semantics into bounded TypeScript side-channel projections while Rust remains execution authority."
series: active
date: 2026-08-31
status: active
construction: in_progress
---

# TS L3 Governance and Evidence Boundary Slice

## Scope

This slice creates the first clean-break TypeScript projections for the
governance/evidence capabilities that surround Python's L3 AgentLoop. The
projections are bounded, data-only, and safe to attach as an event observer.
They do not import Python, spawn subprocesses, write files, mutate memory/R5,
or adjudicate Rust capability requests.

The intended production topology remains:

```text
TS L3 coordination
  ├─ sensitive scan / redact / block metadata
  ├─ compression threshold and breaker decision
  ├─ review + edit-then-verify state
  └─ evidence projection
        ↓ injected durable adapter (future)
L2 session data layer → Rust L1 capability / terminal / process authority
```

## Python-to-clean-break capability matrix

| Python reference | TypeScript projection | Authority after rewrite | Status | Gap / explicit non-goal | Verification |
|---|---|---|---|---|---|
| `l3/agent/sensitive_detect.py` | `l3/governance/sensitive-detector.ts` | TS side-channel policy; Rust still owns execution gates | first slice | SettingsCenter/file persistence and secret-vault semantics stay host-injected; detector remains heuristic | `l3-governance.test.ts`: pattern, redaction, block, bounds |
| `l3/agent/compression_guard.py` | `l3/governance/compression-safety-guard.ts` | TS coordination guard; Rust owns resource/capability limits | first slice | Per-process durable breaker state and PMU linkage require a durable host adapter | `l3-governance.test.ts`: recursion threshold, error storm, reset/window |
| `l3/agent/review.py` | `l3/governance/review-verifier.ts` | Injected reviewer/provider returns data-only verdict | first slice | Peer transport, prompt library, LLM invocation, and card write remain host seams | `l3-governance.test.ts`: verdict normalization and retry/escalation |
| `l3/agent/verify_cadence.py` | `ReviewVerifier` + `VerificationCommandPort` | Host/Rust executor runs commands; TS validates the request and stores only bounded evidence | first command-port slice | TS never invokes shell/process APIs; physical cwd, process handles, and capability policy remain host/Rust responsibilities | `l3-governance.test.ts`: argv/cwd allowlist, cancellation/timeout, output and evidence bounds |
| `l3/tool_system/security_evidence/{models,core}.py` | `l3/governance/evidence-ledger.ts` + `durable-evidence-ledger.ts` | Injected evidence port; in-memory and atomic snapshot implementations are host projections | first durable slice | JSONL metadata sidecar and R5 graph edge remain explicit adapters; no second GateChain | `l3-governance.test.ts`: bounded chain/query/fixity/restart/tamper |
| Python `security_evidence.record_from_metric` | `L3GovernanceBoundary.publish` + `recordRuntimeEvent` | Rust metric sink remains external; TS only projects selected runtime outcomes | first slice | No second GateChain or constitution; no implicit allow on missing evidence | `l3-coordinator-host.test.ts` + governance slice |
| `l3/cell/peers/l3a/session_compress.py` | `scanSensitive` + `checkCompression` | Caller decides whether to proceed; TS cannot perform compression side effects | planned integration | Session compression/storage and R1–R5 persistence remain future L2/R4 adapters | boundary APIs and fail-closed tests |
| `l3/agent/prompts.py`, `prompt_library.py`, `prompt_monitor.py` | existing context projection + future prompt port | Host-provided read-only context | partial | Versioned prompt loading/mutation and bypass monitor need a separate slice | existing context projection tests |
| `l3/memory/skill_promotion.py`, `r4_skill_*` | existing ID-only card/skill links | R4/R5 host authority | not mirrored | Promotion, persistence, and graph writes must not leak into TS runtime | roadmap gap |
| `l3/bus/*`, `error_bus/*` | L2 protocol projection + L3 route/replay values | L2/Rust transport and injected observer | partial | Durable causal bus, cross-process replay, and error persistence remain open | existing routing/replay slices |

## Implemented contract

### Sensitive detector

`SensitiveDetector` uses the same bounded heuristic classes as the Python
reference (API keys, bearer tokens, private-key markers, IPv4, IPv6). `scan`
returns detached hit metadata and a redacted text view only when the configured
action is `redact`. The `block` action is a caller-visible decision; it does not
reach the execution port.

### Compression guard

`CompressionGuard` carries the reference semantics that matter at the
coordination boundary:

- recursive compression is disabled by a zero threshold by default;
- a breaker can pause work after a threshold breach or an error storm;
- successful passes clear the error burst;
- operator reset is explicit;
- an optional trip callback is best-effort evidence only.

### Review and verification cadence

`ReviewVerifier` normalizes untrusted verdict values to `PASS`,
`NEEDS_CHANGES`, or `REJECT`, bounds reasons/suggestions, and implements the
retry/escalation transition. The same object tracks edited paths, emits a
bounded nudge, and stores command-result evidence. It intentionally does not
run a command.

`VerificationCommandPort` is the explicit host-injected command seam. It accepts
only detached argv values, checks an allowlist and project-root cwd boundary,
propagates timeout/cancellation, and bounds stdout/stderr by UTF-8 bytes. The
executor is supplied by the host or Rust adapter; this module never imports a
shell, subprocess, PTY, or process handle. A missing port is a fail-closed
result that is still projected into the review/evidence side channels.

### Evidence ledger

`InMemoryEvidenceLedger` is a bounded append-only projection with:

- per-kind chain reuse and explicit close;
- bounded labels and raw snapshots;
- SHA-256 raw and predecessor hashes;
- detached newest-first query/snapshot values;
- retained-window verification with an eviction base hash;
- selected runtime event projection that records rejection/failure metadata
  without copying event payloads.

`EvidencePort` is the replacement seam for a future durable outbox/JSONL/R5
adapter. `DurableEvidenceLedger` now wraps the same append-only projection with
an injected `DurableEvidenceStorage`, commits complete versioned documents,
rolls back failed commits, and validates state before restart. The default
`MemoryEvidenceStorage` is test-only; `JsonFileEvidenceStorage` is an explicit
host adapter and is never created implicitly by L3.

### Durable evidence adapter

The durable document contains the retained points, chain summaries, sequence
counters, predecessor anchor, and latest hash. A restart reconstructs the
in-memory projection only after row, predecessor, raw-hash, and sequence
validation. Storage failure restores the pre-operation document, so a failed
commit cannot leave the live projection ahead of durable state.

### Host composition

`createL3CoordinatorHost()` accepts an optional `L3GovernanceBoundary` and
places it after replay and L2 projection in deterministic event fanout. The
governance observer is detached from the external observer and can never
change a Rust receipt or L2 result.

## Invariants

1. Rust remains the only process, terminal, capability, and hard-constraint
   authority.
2. Governance failures are side-channel failures and do not recursively fail
   `AgentRuntime`.
3. No source text, provider object, executable handler, or process handle is
   retained by the evidence projection.
4. Every report, queue, reason, label, and raw snapshot is bounded.
5. An unrecognized review verdict becomes `NEEDS_CHANGES`; a blocked
   compression check remains blocked until explicit reset.
6. Durable recovery, R5 graph linkage, SettingsCenter hydration, and the
   physical command executor require explicit injected ports; the TS command
   port is validation/evidence only.

## Verification slice

Run from the TypeScript engine directory with the Linux Node toolchain:

```bash
/home/guiling/.nvm/versions/node/v24.19.0/bin/node \
  /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/typescript/bin/tsc \
  --noEmit -p tsconfig.json \
  --typeRoots /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/@types

/home/guiling/.nvm/versions/node/v24.19.0/bin/node \
  /home/guiling/dev/praxis/systems/typescript-shell-engine/node_modules/vitest/vitest.mjs \
  run --pool=threads --maxWorkers=4 \
  tests/l3-governance.test.ts \
  tests/l3-coordinator-host.test.ts \
  tests/l3-coordinator.test.ts
```

Observed slice evidence: typecheck clean; the governance slice passes 12 tests,
including memory/file restart, commit rollback, tamper rejection, command
allowlist/cwd bounds, cancellation/timeout, output caps, and fail-closed
missing-port evidence. The broader L3 slice remains separate evidence and this
is not full-suite, cross-process locking, or Rust-owned crash evidence.

## Next construction seams

1. Mirror versioned prompt-library reads and bypass telemetry without allowing
   TS to mutate Python/R5 stores.
2. Add fixed-work governance and L2 outbox performance baselines
   (throughput, p50/p95/p99, RSS, queue contention, rejection counts).
