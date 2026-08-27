---
name: card-scheduler-architect
description: Use when writing or modifying Praxis card and cell execution code — CardRegistry lifecycle, card pool, planner, decomposer, execution engine (rollback/recovery), dialogue sessions, scheduler, or CentralController (systems/python-reference-runtime/l3/cell/peers/l3.py).
---

## Overview

Architecture guide for the card execution system (`systems/python-reference-runtime/l3/card/`, `systems/python-reference-runtime/l3/cell/`) and its scheduler. Work enters the system as cards (`python main.py card "<intent>"`), is planned, decomposed, executed with rollback safety, and converged back.

## Module Map

- **Lifecycle**: `card_registry.py` (CardRegistry — submit/dispatch/complete lifecycle), `card_pool.py` (install from URL/file, export, `search_remote`, `sync_from_peers`, remove)
- **Planning**: `planner.py` (HTN/step planning), `decomposer.py` (`decompose` → `confirm` → `dispatch_to_cell` → `converge`; `get_decomposer()`/`reset_decomposer()`)
- **Execution**: `execution_engine.py` (ExecutionPlan/ExecutionResult; topological sort of steps, `_execute_with_retry`, dependency checks, recovery modes abort/retry/skip/rollback; rollback handlers via `register_rollback(tool_name, handler)` with defaults for replace/file-create/rename)
- **Verification**: `execution_verify.py` (scout + diff verify + consistency checks)
- **Collaboration**: `dialogue_session.py` (per-agent dialogue, `create_session`/`get_session`/`close_session`), `issue.py` (IssueCard + registry), `convention.py` (structured debate: propose/cross_examine/rebut/close, document generation)
- **Persistence**: `card_persistence.py`, `plan_step_types.py` (step timing)
- **Orchestration**: `systems/python-reference-runtime/l3/cell/peers/l3.py` — CentralController: L3A sessions + L3B routing + CardRegistry lifecycle; `systems/python-reference-runtime/l3/scheduler/` owns dispatch timing/queues; `systems/python-reference-runtime/l3/cell/` Cell objects bind agents + skills.

## Conventions

- **Lifecycle discipline**: cards move submit → dispatch → complete/fail through CardRegistry; new entry points must go through the registry, not bypass it.
- **Execution safety**: recovery handlers must make progress (abort/retry/skip/rollback); register rollback handlers for any tool that mutates the filesystem; `_trim_executions_locked` bounds history.
- **Staged-skill linkage**: `on_card_complete` advances the card session's stages — the three-table linkage (card ↔ session ↔ skill stages) must stay intact when refactoring card completion.
- **Cell bindings**: `Cell.bind_skills(names)` white-lists skills per Cell (config `cell.skills` in `config/praxis.yaml`); unbound Cells fall back to the global pool. AgentLoop context injection filters by `cell_id`.
- **Decomposition**: `dispatch_to_cell` maps slices to agents/cells; `converge` merges results — keep convergence idempotent so retried converges do not double-apply.
- **Singleton discipline**: registry/pool/engine have `get_*()` + `reset_*()`; new ones must register resets in `tests/conftest.py` `_RESETS`.
- **Constants**: scheduler timings, retry budgets, pool sizes go in params (`systems/python-reference-runtime/l1/kernel/params/`) — never inline.

## Tests

- `python -m pytest tests/ -k "card or scheduler or cell" -x -q` (orchestration-heavy cases in Batch 2 via `tests/runner.py --batch 2`).
