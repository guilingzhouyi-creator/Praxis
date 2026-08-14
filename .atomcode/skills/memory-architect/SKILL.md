---
name: memory-architect
description: Use when writing or modifying Praxis memory subsystem code — R4Agent skill evolution (evolve/generalize/trace/lifecycle), skill persistence round-trip, R5 memory graph, memory ingest/search/compact, and the memories/ persistence layer.
allowed-tools: Read, Grep, Glob, Write, Bash
---

## Overview

Architecture guide for the Praxis memory and skill subsystems (`src/l3/memory/`, ~29 modules). Use it when touching R4Agent skill workflows, memory persistence, or the R5 graph so conventions stay intact.

## Module Map

- **Facade**: `memory.py`, `central_memory.py`, `memory_init.py`, `memory.py`
- **Persistence**: `memory_persist.py`, `memory_compact.py`, `memory_mer.py`
- **Ingest/query**: `memory_ingest.py`, `memory_search.py`, `memory_query.py`, `memory_inject.py`, `memory_context.py`, `memory_quality.py`, `memory_ring.py`, `skill_retrieval.py`, `skill_retriever.py`
- **R4Agent (skill evolution)**: `r4_agent.py` (orchestrator) + `r4_skill_evolution.py`, `r4_skill_generalize.py` (`evolve_skill`), `r4_skill_trace.py` (`_process_failure_traces` — lean cases), `r4_skill_lifecycle.py` (`_prune_stale_skills` TTL, `_clean_orphan_traces` 24h), `r4_skill_persist.py`, `r4_skill_retrieval.py`, `r4_skill_feedback.py`, `r4_skill_distill.py`
- **R5 graph**: `memory_graph.py`
- **Skill manager**: `src/l1/kernel/skill.py` (SkillManager), `src/l1/kernel/prompts.py` (prompt registry — prompt templates are data, not params)

## Skill Evolution Conventions (R4Agent)

- **Round-trip integrity**: `evolve_skill` persists `SKILL.md` with full YAML frontmatter (`name`, `description`, `tags`, `allowed_tools`, `variables`, `posture`, `disclosure`, `dependencies`/`dependency-kind`, `next`, `stages`); `_load_markdown` must restore ALL of these on reload. Never add a persisted field to one side without the other.
- **Write gate**: `authorize_write(agent_id, role, internal=False)` — external callers (L2 `/skills`, L4 API) MUST pass an explicit identity; only system processes (boot loading, R4Agent) use `internal=True`. Never weaken it; it also guards Cell bindings and TTL prune deletes.
- **Per-Cell injection**: `Cell.bind_skills(names)` white-lists skills; `AgentLoop._inject_extra_context` filters by `cell_id`; unbound Cells fall back to the global pool. Config: `cell.skills` in `config/praxis.yaml`.
- **Layered persistence**: `skill.evolve_scope` — `project` (default → `<package-root>/skills/evolved`) or `global` (→ `data_dir/skills/evolved`). Keep the discovery dirs in `paths.py` CLI_PROJECT list in sync with the write target or evolved skills vanish on reboot.
- **R4/R5 linkage**: evolution archives the pre-evolution version (`fonds="skills", series="evolved"`), TTL prune archives before delete (`series="pruned"`), failure traces archive as `series="lean_trace"`. With the R5 graph enabled, add `refines`/`type_chain` edges (evolution) and `depends_on` edges (lean cases); ALL graph calls are non-blocking and degrade to linear fallback (try/except) — graph is OFF by default (`memory.graph.enabled`).
- **Dedup**: lean-case dedup matches exact name or `dedup_key + "_"` prefix — never raw substring (`rm` vs `rmdir` collision).
- **Atomic counters**: use `SkillManager.bump_usage(name)` (single-lock RMW) — never get-then-update in callers.
- **Audit**: skill mutations emit `skill_mutated` via `get_bus().emit_event(...)`, NOT `emit_signal` (SignalType has no member for it — emit_event auto-registers the string type).
- **Shared principles**: the 12 universal governance principles live ONCE in `config/skills/_shared/principles.md`, injected by the loader — never duplicate in per-skill files.
- **Disclosure depth** (`full|index|none`): `none` hidden from catalog/retrieval/injection (explicit `use_skill` only); `index` surfaces name+description only; `none`-tagged skills skip the retrieval pool.
- **Staged skills**: `current_stage`/`advance_stage` per-session; `use_skill` discloses only the active stage; `dependencies` + `next` form the guidance DAG (`guided_frontier`/`guided_path`, acyclicity enforced); `on_card_complete` advances the card session's stages (three-table linkage).
- **Structured view**: agents consume `SkillManager.structured_skill()` (rules/procedures/stages, no markdown body); `list_skills()` drops `prompt` on external surfaces; `use_skill` defaults to structured view, `full=true` is a write-gated privileged read.

## Memory Conventions

- **Weights in params**: `MEMORY_IMPORTANCE_*` / `MEMORY_PRESSURE_*` from `src/l1/kernel/params/system.py` — never inline.
- **Persistence**: `memories/` runtime persistence via memory_persist; compaction via memory_compact; keep serialized formats backward-compatible or versioned.
- **Conftest**: new memory services with module-level singletons must register their reset function in `_RESETS` (`tests/conftest.py`), else tests pollute each other.

## Gates

- `tests/infra/test_skill_schema.py` enforces the normalized skill contract (required fields, enum validity, trigger-oriented description, name=directory, dangling refs, guidance-DAG acyclicity, body layout, loader round-trip).
- Full memory suite: `python -m pytest tests/ -k "memory or r4 or skill" -x -q` (slow cases in Batch 2 via `tests/runner.py --batch 2`).
