---
pointer: ROADMAP-2026-08-18-006
archive_number: ROADMAP-2026-长期-006
fonds: ROADMAP
year: 2026
retention: 长期
title: "Engineering Debug Mode Roadmap (3.5)"
author: L3
formation_date: 2026-08-18
carrier: md
classification: 内部
pages: 87
archivist: L3
reviewer: L3
archive_date: 2026-08-29
source: roadmap
keywords: []
abstract: "Engineering debug mode is a developer-only operating mode layered on top of"
series: active
date: 2026-08-18
status: active
construction: in_progress
---

# Engineering Debug Mode Roadmap (3.5)

> Status: implementation merged, P1 gaps open (P1-C closed — see §3). This
> roadmap records the completion boundary for 3.5 and the work required before
> it can be marked complete. Review evidence:
> [engineering-debug-review](../design/reviews/2026-08-16-engineering-debug-review.md).

## 1. Scope and decision

Engineering debug mode is a developer-only operating mode layered on top of
the production runtime. Production remains the default. The marker file is a
hard activation gate; it is not an authorization mechanism. Authorization,
privacy, and observability must remain independent gates so that a normal user
cannot turn on engineering controls by changing ordinary runtime settings.

The feature was merged by `231ae77` (implementation: `d603bde`). It is
therefore **implemented but not complete**: the baseline behavior is usable,
while the P1 findings below must be closed before the status changes to
`Complete`.

## 2. Delivered baseline

| Area | Current behavior | Evidence |
|---|---|---|
| Mode selection | `auto` resolves to production unless `.praxis/debug_mode.flag` exists; symlink markers are rejected | `engineering_debug.py` |
| Control surfaces | Dedicated `/api/v2/engineering-debug*` routes and `/debug-mode`/`/debug-input` L2 commands | API and shell handlers |
| Logging | Debug logging is enabled on entry and restored on exit | engineering debug manager |
| Prompt management | Developer prompt overlays, version metadata, rollback, and baseline restoration | `l1.kernel.prompts` integration |
| Prompt monitoring | Bypass observations are best-effort published through EventBus, ReferenceChannel, and StatsCenter | `prompt_monitor.py` |
| Input privacy | Port contract exposes aggregate keyboard/pointer activity only; no key values or pointer coordinates are retained | `InputActivityPort` / `InputActivitySnapshot` |
| Verification | Focused slice tests pass: 13 tests in engineering-debug and input-activity suites | `tests/l3/tool_system/` |

## 3. Open work, ordered by priority

### P1 — close before declaring 3.5 complete

| ID | Gap | Required outcome | Acceptance evidence |
|---|---|---|---|
| P1-A | **Generic settings bypass identity checks.** `/api/v2/settings` and `/settings global set` can write `engineering_debug.*`, including `marker_file`, without the dedicated developer/ring gate. | Route every engineering-debug write through one authorization service. Ordinary settings writes must reject the namespace, and marker paths must be constrained to the deployment workspace and regular files. | Unauthorized API and L2 tests; authorized developer/ring-3 tests; traversal, outside-workspace, and symlink rejection tests. |
| P1-B | **Hardware input monitoring is not implemented.** The runtime currently has only `NoopInputActivityPort` and `FakeInputActivityPort`. | Add platform adapters behind `InputActivityPort` for keyboard and pointer activity, with explicit permission/unavailable states and an aggregate-only contract. | Linux/WSL adapter smoke test (or deterministic unavailable result); no raw input in snapshots, logs, persistence, or events. |
| P1-C | ~~**Provider start failure leaves false enablement.** A `False` return from `provider.start()` can persist `enabled=True`.~~ **✅ Closed** — enablement is now transactional: `_enabled` is claimed only when `provider.start()` succeeds, rolled back to the previous state on failure, and the persisted setting is synced (`rolled_back` reported). | Treat provider startup as transactional: on failure roll back `_enabled` and persisted configuration, return a failed result, and expose `enabled=False`. | `systems/python-reference-runtime/l3/tool_system/input_activity.py` `sync_from_mode`/`set_enabled` implement the P1.6 transactional enable (shipped with agent-os-3x-closure Slice E); input-activity slice tests cover it (`tests/l3/tool_system/test_input_activity.py`). |
| P1-D | **Production mode can read engineering prompt details.** Prompt status/listing is not gated even though prompt writes are gated. | In production, return only redacted metadata (or an explicit unavailable result); expose layers/previews/versions only after the engineering-mode gate. | Production read test proves no prompt text, preview, or overlay version leaks; debug read test remains available to authorized callers. |
| P1-E | **Input privacy configuration can drift from the invariant.** `capture_content` is configurable while status surfaces hard-code `False`. | Make the privacy invariant single-source: remove the writable setting or reject `True`, return an explicit `disabled_by_policy` state, and test all config layers. | Config mutation test; status/API/L2 output and persisted state agree; raw-content regression test. |

### P2 — harden after P1

| ID | Gap | Required outcome |
|---|---|---|
| P2-A | Defaults are repeated across params, kernel settings, SettingsCenter, discovery, and deployment config. | Keep params as the source of truth and add a consistency check or generated registration for the remaining layers. |
| P2-B | Transition telemetry silently discards all channel errors. | Preserve best-effort degradation but emit a debug diagnostic with trace context and a failure counter. |
| P2-C | A private command helper is imported across L2 command modules. | Move it to a shared command utility or make the contract explicitly public before the TS mirror is generated. |
| P2-D | The manager mixes lifecycle, prompt registry, and module-level singleton concerns. | Split only when needed for testability or the TypeScript contract; preserve the public manager/port surface. |

## 4. Execution phases

1. **Authority and privacy gate (P1-A, P1-D, P1-E).** Define the protected
   namespace, centralize authorization, constrain marker paths, redact
   production reads, and make the aggregate-only input contract explicit.
2. **Platform provider (P1-B, P1-C).** Implement the OS adapter through the
   kernel port, model permission/unavailable states, and make start/stop
   transitions transactional.
3. **Configuration and observability hardening (P2-A to P2-C).** Remove
   duplicate defaults, add diagnostics for degraded telemetry, and stabilize
   the helper/command boundary.
4. **TS/Rust rewrite preparation.** Freeze versioned JSON schemas for mode,
   prompt metadata, and input snapshots. TypeScript must consume the API/port
   contract and never read devices or bypass authorization directly; a future
   Rust adapter may own platform input through the same port. Keep Python3 as
   the current reference implementation until contract and parity tests are
   green.

## 5. Completion gate

3.5 may move from `implementation merged, P1 gaps open` to `Complete` only
when:

- P1-A through P1-E have code and regression tests;
- the focused 3.5 slices and the full documented test gates pass;
- layer-import, params/config consistency, privacy, and API contract checks
  are green;
- production/debug transitions have evidence records and traceable failures;
- the CompletionJudge reports `COMPLETE`, the worktree is clean, and the
  implementation and architecture docs are synchronized.

The hardware adapter remains an explicit platform capability. An unavailable
or permission-denied platform must degrade to a visible, non-recording state;
it must never silently claim that input monitoring is enabled.
