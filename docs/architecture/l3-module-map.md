# L3 Module Map — functional domains, ownership, naming

> Reference contract for L3 normalization and the future TypeScript rewrite.
> **Maintenance rule**: any module add/move/rename updates this map in the
> SAME commit. Status claims without a matching tree state are drift.
>
> Survey basis: main @ `ba396896` (2026-08-23), post-normalization + rust-preflight merge.
> **TS mirror status**: `packages/protocol-ts/` — 20 modules, 77 tests, tsc clean. See §8.
> Regenerate counts anytime with:
>
> ```bash
> for d in src/l3/*/; do echo "$d $(find "$d" -maxdepth 1 -name '*.py' | wc -l)"; done
> ```

## 1. Ownership domains (7-domain partition)

| Domain | L3 territory (dirs) | Single writer |
|---|---|---|
| **M** memory | `memory/`, `durable_store.py` (cross-domain persistence base) | M-agent |
| **S** sessions | `cell/peers/l3a/`, `card/dialogue_session.py`, `discussion/answer_session.py`, `agent/session_snapshot.py`, `services/session_export.py` | S-agent |
| **T** tools | `tool_system/`, `tools/`, `services/file_editor*`, `services/fs*` | T-agent |
| **C** card/cell | `card/`, `cell/`, `scheduler/`, `discussion/` (orchestration side), `services/cell_orchestrate.py`, `services/card_tool_stats.py` | C-agent |
| **B** bus | `bus/`, `error_bus/` | B-agent |
| **A** bridge/services | `services/model_service.py`, `model_strategy.py`, `identity.py`, `content_trust.py`, `central_security.py`, `approval_policy.py`, `capability_store.py`, `user_profile.py` | A-agent |
| **K** kernel | none in L3 (L1 only; L3 consumes via ports) | — |

Cross-domain shared infrastructure (single-writer, changes announced):
`_persistable.py`, `durable_store.py`, `params.py`, `ports.py`, `_pool.py`,
`_daemon_pool.py`, `_base.py` (L3 root).

## 2. Directory × function × domain matrix

| Dir | Files¹ | Primary function | Domain |
|---|---|---|---|
| `l3/` root | 9 | shared bases + persistence infra + net client | cross / A |
| `agent/` | 38 | AgentLoop entity family, prompt assembly/library/monitoring, subagent framework, terminal handler privates (`_term_*`) | S+C hybrid (loop=S/C; prompts=A; term=C) |
| `agent_terminal/` | ~4 | terminal binding package (worker pool, card execution mixin) — shares the terminal family with `agent/_term_*` | C |
| `boot/` | 6 | 7-step bootstrap, wiring→ports, lifecycle/factory reset | K-side consumer |
| `bus/` | 17 | task/message buses, L3B composites chain, HTN planning, observability mirrors | B |
| `card/` | 27 | CardUnified lifecycle, registry, dispatch, execution plan/engine | C |
| `cell/` | 4 + components 26 + peers | Cell orchestration (components family) + peers (`l3a/` central decision, `l3.py` controller) | C (+S for peers/l3a) |
| `config/` | 3 | discovery-driven config loading | cross |
| `discussion/` | 7 | cross-cell deliberation (issue → answers → report) | C |
| `error_bus/` | 6 | unified trace_id + capture() error records | B |
| `memory/` | 47 | R1–R5 rings, refinement, skill evolution/candidate ledger/promotion | M |
| `resource_buffer/` | ~4 | bounded resource pools | C |
| `scheduler/` | 11 | routing/scope/rate/time schedulers, think registry, ACB, loop detectors | C |
| `services/` | 46 | mixed bag — see §4 decomposition plan | A/T/C split |
| `tool_system/` | 19 (+`security_evidence/`) | pipeline/registry/spec/policy, presentation modes, harness, engineering debug, input activity | T |
| `tools/` | 22 | concrete tool handlers (`_*.py`) registered via `tools.yaml` | T |

¹ `.py` count including `__init__.py`; regenerate per header command.

## 3. Adjudications (2026-08-22 survey)

| Suspected duplicate | Verdict |
|---|---|
| `services/todo.py` vs `services/todo_tracker.py` | **Legit split** — TodoTable = priority/dependency queue; TodoTracker = AgentLoop task state machine (pending→verifying→verified). No merge; both mapped. |
| `card/models.py` vs `card/card_models.py` | models.py is a **deprecated bridge** (old Card/Phase enums for `CardUnified.to_old_card()`); remaining consumers: `card/execution_run.py`, `cell/components/cell_decompose.py`. Migration tracked in slice B2. |
| `bus/l3b.py` vs `bus/l3b_bus.py` | **Two layers, one family**: l3b.py = composite coordinator (HTN-B + AgentLoop, chain topology); l3b_bus.py = inter-composite mailbox bus. Renamed to `l3b_composite.py` in slice B3 for disambiguation. |

## 4. Cross-directory families (index, not merges)

- **cache family** (6 impls, distinct roles — do NOT merge blindly):
  `memory/cache.py` (isolated ring cache), `memory/cache_doc.py` (docs),
  `memory/tiered_cache.py` (3-layer cross-cell, P1.1-persisted),
  `cell/components/cell_cache.py` (cell hot zone),
  `agent/tool_result_cache.py`, `agent/digest_cache.py`,
  `tool_system/run_code_cache.py` (per-cell program cache).
- **session family**: `l3a/` session system (authoritative, S),
  `card/dialogue_session.py` (card-bound dialogue),
  `discussion/answer_session.py` (deliberation answers),
  `agent/session_snapshot.py`, `services/session_export.py`.
- **prompt family**: `agent/prompts.py` (runtime, moved out of L1 WS5.3 — shim kept),
  `agent/prompt_library.py` + `global_prompt_library.py`, `agent/prompt_monitor.py`
  (P1.2 versioned telemetry), `services/prompt_engine.py`.
- **model family**: `services/model_service.py` + `model_strategy.py` (A),
  `l4/llm/*` (bridge), `l3a/model.py` (session-scope config).
- **identity family**: `services/identity.py`, `services/content_trust.py` (A),
  `l1/kernel/identity_binding` (kernel-side).

## 5. Root-level disposition

| File | Disposition |
|---|---|
| `durable_store.py` | Cross-domain persistence base (P0.4). Owner: M. Envelope `{v, kind, checksum, payload}` is the TS-mirrorable storage protocol. |
| `net_client.py` | **Stays at root** — generic stdlib HTTP utility with a documented canonical home (`from l3.net_client import NetClient`); relocation would churn C-domain consumers for zero gain. |
| `params.py` / `ports.py` | Convention surface — stays at root. |
| `_base.py` / `_pool.py` / `_daemon_pool.py` / `_persistable.py` | Shared bases — stay; registered as cross-domain single-writer infra. |

## 6. Naming rules (recap + status)

- Module files snake_case, directories kebab-case — **no violations found** in L3.
- Prefix families are stable names, NOT subpackage debt: `cell/components/cell_*` ×26,
  `agent/agent_loop*` ×7, `subagent*` ×9, `r4_skill*` ×8, `memory_*` ×16.
  Documented here; renaming them is explicitly out of scope.
- Planned moves (normalization slices): `services/file_editor*` ×5 → subpackage;
  `bus/l3b.py` → `l3b_composite.py`; `net_client.py` → `services/`.

## 7. Slice ledger (normalization branch `feature/l3-normalize`)

| Slice | Scope | Status |
|---|---|---|
| A1 | this map | this commit |
| B3 | `l3b.py` → `l3b_composite.py` + six-step reference sweep | **Complete** (f56d27bc) |
| B1 | `services/file_editor*` → subpackage | **Complete** (facade preserved as package `__init__`; route strings resolve unchanged) |
| B2 | `card/models.py` migration adjudication | **Blocked** — `to_old_card` has zero callers but `cell_decompose.py` constructs legacy Card/Phase sub-cards; needs CardUnified constructor parity (follow-up slice) |
| B5 | `net_client.py` relocation | **Adjudicated: stays at root** |
| A2/A3 | runtime-subsystems counts + README registration | **Complete** |


## 8. TS Mirror Status (`packages/protocol-ts/`)

The L2 TS engine is under active rewrite. The following modules are
implemented and tested (62+ tests, tsc clean):

| Module | Lines | Mirrors | Status |
|---|---|---|---|
| `envelope.ts` | ~218 | `l2/protocol/envelope.py` | ✅ ring-buffer Outbox |
| `records.ts` | 325 | `l2/protocol/records.py` | ✅ |
| `types.ts` | ~100 | (type-level only) | ✅ branded IDs + discriminated union |
| `engine/bridge.ts` | ~207 | `l2/protocol/host.py` (client side) | ✅ AsyncGenerator stream, batch, timing |
| `engine/parser.ts` | 37 | `l2/l2_shell/__init__.py` dispatch | ✅ fast path for unquoted |
| `engine/dispatcher.ts` | 84 | `l2/commands.py` registry | ✅ wildcard + lazy sort cache |
| `engine/builtins.ts` | 40 | lang/help/clear builtins | ✅ |
| `engine/session-manager.ts` | 136 | ProtocolHost multiplexing | ✅ non-destructive ack |
| `engine/session.ts` | 129 | SessionView projection | ✅ |
| `engine/session-family.ts` | 115 | ShellFamily registry | ✅ |
| `engine/route.ts` | 96 | Dialect routing classifier | ✅ pure parseRoute |
| `engine/selector.ts` | 95 | Dict data API projection | ✅ zero object handles |
| `engine/completer.ts` | 64 | Tab completion | ✅ |
| `engine/output-guard.ts` | 55 | Display safety mirror | ✅ degrade-to-allow-through |
| `engine/command-groups.ts` | 73 | Command grouping | ✅ |
| `engine/cot-guard.ts` | 66 | CoT privacy boundary | ✅ sanitize + detect |
| `engine/middleware.ts` | 69 | Composable pre/post hooks | ✅ LIFO/FIFO chain |
| `engine/message-pool.ts` | 91 | Message object pool | ✅ reset-and-reuse |
| `engine/l3-bridge-interface.ts` | 61 | Typed L3 command surface | ✅ domain-grouped IL3Bridge |
| `engine/errors.ts` | 66 | Structured errors with codes | ✅ ProtocolError + retry |
| `engine/health.ts` | 57 | Bridge health probe | ✅ periodic latency check |
| `engine/connection-manager.ts` | 84 | Transport lifecycle FSM | ✅ retry + state machine |
| `engine/projection-cache.ts` | 45 | WeakRef projection memoisation | ✅ GC-friendly |
| `engine/config-reader.ts` | 56 | SettingsCenter read mirror | ✅ TTL cache |
| `engine/broadcast.ts` | 57 | BroadcastChannel multi-tab | ✅ EventTarget pub/sub |
| `engine/bench.ts` | 50 | Micro-benchmark harness | ✅ drift detection |
| `i18n.ts` | 64 | Locale data consumption | ✅ |
| `transports/*` | 4 adapters | stdio/http/ws/ssh | ✅ |

**Not mirrored (Python3-only authority):**
AgentLoop, Tool Pipeline, Workflow, Scheduler, Memory promotion,
Skill mutation, Card lifecycle, Config write authority.
