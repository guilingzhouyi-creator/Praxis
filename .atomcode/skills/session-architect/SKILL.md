---
name: session-architect
description: Use when writing or modifying Praxis session subsystem code — L3A session system (session lifecycle, history, compression, persistence, subagents, context epochs, ask state machine, secretary), or CentralController integration in src/l3/cell/peers/l3a/.
---

## Overview

Architecture guide for the L3A session system (`src/l3/cell/peers/l3a/`, 23 modules) and its CentralController integration (`src/l3/cell/peers/l3.py`). Use it when adding session features, fixing session persistence, or wiring L2/API routing.

## Module Map

- **Daemon**: `__init__.py` (daemon + singleton accessors)
- **Core**: `session.py` (Session/Manager), `session_history.py` (Page/Message/SessionHistory model), `session_ask.py` (ask-state), `session_compress.py` (transcript compression), `session_prompt.py` (prompt assembly), `session_loop.py` (per-session agent loop), `session_persist.py` (durable session state)
- **Concurrency**: `subagent.py` (L3ASubAgentPool), `context.py` (ContextEpoch/Registry), `inbox.py` (PromptInbox)
- **R4/LLM glue**: `summaries.py` (summary + R4), `model.py` (L3AModelConfig), `archive.py` (R4 store/restore), `pipeline.py` (ManagedToolOutput)
- **Coordination**: `task_table.py` (task monitor), `helpers.py` (cardwrite/convergence), `api.py` (L2 routing), `agents_md.py` (AGENTS.md generator), `types.py` (enums/dataclasses), `params.py` (constants), `ask.py` (clarification state machine), `secretary.py` (L3A-C: capability-threshold assist → peer upgrade)
- **Owner**: `src/l3/cell/peers/l3.py` — CentralController: L3A sessions + L3B routing + CardRegistry lifecycle

## Conventions

- **Singleton discipline**: daemon lives in `__init__.py`; expose `get_*()` accessors AND a reset function — new services must register their reset in `_RESETS` (`tests/conftest.py`), or the autouse fixture cannot isolate them.
- **Thread safety**: use `threading.RLock()` reentrant locks with `with lock:`; never bare `except:`.
- **Durability**: session state (history, ask state, task table) persists through `session_persist.py`; keep serialized formats versioned — restoring an old page layout must not crash the daemon.
- **Context epochs**: `context.py` ContextEpoch/Registry boundaries group context by epoch; do not leak context across epochs. Compression (`session_compress.py`) truncates transcripts before context overflow — verify the format this repo's `LOG_TRUNC_*`/`HASH_TRUNC_*` params prescribe.
- **Subagent pool**: `subagent.py` bounds concurrency; cleanup on session close is mandatory (no orphan workers).
- **Secretary (L3A-C)**: capability-threshold model — assist-level work stays in-session; only above-threshold work upgrades to a peer (`secretary.py`). Don't bypass the threshold when adding new assist paths.
- **Card linkage**: `helpers.py` cardwrite/convergence bridge sessions to cards; `on_card_complete` advances staged-skill progression (three-table linkage) — keep the coupling one-directional session → card.
- **L2 routing**: L2 shell commands reach sessions through `api.py` — never import L2 from L3A internals.
- **Constants**: all magic numbers (timeouts, page sizes, compress thresholds) go in `l3a/params.py` — never hardcode.

## Tests

- `python -m pytest tests/ -k "l3a or session" -x -q` (orchestration-heavy cases live in Batch 2 via `tests/runner.py --batch 2`).
