# Praxis — Agent OS (v0.4.2 "Aether")

Python 3.11+ Agent OS for orchestrating LLM-based agents. Five-layer architecture from bare-metal kernel to user CLI.

> **This file is an index.** It carries the load-bearing rules every agent must
> obey and points to the detailed docs in `docs/` for everything else. Read the
> linked doc before touching the subsystem it describes. `CLAUDE.md` is a thin
> Claude-Code-facing pointer to this file — keep the rules here, not there.

## Doc index

| Area | Entry points |
| --- | --- |
| Architecture (layers, module maps, contracts) | `docs/architecture/README.md` + per-layer docs (linked in `## Architecture`) |
| Workflow — commits, gates, push | `docs/workflow/commits.md` |
| Workflow — branching, accumulation gate | `docs/workflow/branching.md` |
| Workflow — parallel agents | `docs/workflow/collaboration.md` |
| Build discipline — worktree, waivers, DoD | `docs/workflow/code-of-conduct.md` |
| Repo layout & naming rules | `docs/project-structure.md` |
| Runtime system boundaries | `systems/README.md` + `systems/system-boundaries.yaml` |
| Config system | `docs/configuration/overview.md` |
| Automation perimeter | `docs/architecture/automation.md` |
| Memory / skill / security / sandbox specs | `docs/architecture/l3-memory.md`, `skill-system.md`, `security-evidence.md`, `sandbox-diff.md` |

## Quick start

```bash
pip install -e ".[test]"                       # install + dev deps
python systems/python-reference-runtime/main.py boot|health|status|ps|card  # kernel lifecycle + dispatch
python -m l2.l2_shell                          # interactive L2 Shell
```

## Test commands

All commands inside the repo venv (`.venv/bin/python`). Full suite: `python -m pytest tests/ -x -q`.
Batch splits: `python tests/runner.py --batch 1|2`. Single file: `python -m pytest tests/l1/test_kernel.py -x -q`.
Lint: `make lint|format|typecheck`. Coverage: `make coverage`. Gates: `make precommit`.

## Architecture

Layer map (details: `docs/architecture/README.md`):

```
systems/python-reference-runtime/ — Python technical prototype and semantic baseline
systems/rust-kernel-engine/       — independent Rust formal-kernel rewrite
systems/typescript-shell-engine/  — independent TypeScript formal shell/protocol rewrite
tests/ + scripts/ + config/ + docs/ — build and verification perimeter only

systems/python-reference-runtime/l5/ — User layer: cli.py, agent_runtime.py
systems/python-reference-runtime/l4/ — Bridge: API gateway, LLM engine+providers, sandbox, MCP, search, LSP, vault
systems/python-reference-runtime/l3/ — Cell layer: agents, memory, cards, scheduler, tool pipeline, discussion
systems/python-reference-runtime/l3/cell/peers/l3a/ — L3A orchestration daemon: session system, subagent pool, context epoch
systems/python-reference-runtime/l3/cell/peers/l3.py — CentralController (L3A+L3B+CardRegistry)
systems/python-reference-runtime/l2/ — Shell family: shells/ dialect adapters, l2_shell engine, protocol v1 wire contract
systems/python-reference-runtime/l1/kernel/ — Kernel primitives: sync, event, constitution, allocator, gatechain, VFS, IPC, params/
systems/python-reference-runtime/l1/kernel/ports/ — 18 *Port(ABC) abstractions
```

### Import rules (enforced by `tests/infra/test_layer_imports.py`)
- L5→L4→L3→L2→L1 only; L1 cannot import upper layers; 130 pre-existing cross-layer imports allowlisted
- The three runtime systems cannot import one another's source; run `make system-boundaries`
  (enforced by `tests/infra/test_system_boundaries.py`)

## Key conventions

- **All magic numbers in `systems/python-reference-runtime/l1/kernel/params/`** — never hardcode in implementation files
- **New kernel modules** exported in `kernel/__init__.py __all__`
- **New config items** register defaults in `kernel/settings.py DEFAULTS`
- **Use `threading.RLock`** for reentrant locks; plain `threading.Lock` for flat sections
- **Unified `trace_id`**: `get_trace_id`/`set_trace_id`/`trace_scope` in `systems/python-reference-runtime/l3/error_bus/core.py`
- **Never import `services/` inside `kernel/`**
- **Register tools** via `ToolSpec` in `config/tools.yaml`
- **No bare `except:`** — use `except Exception:`
- **Double quotes** for strings (ruff `quote-style = "double"`), line-length 120
- **Prompt templates are data** in `systems/python-reference-runtime/l3/agent/prompts.py` (`_DEFAULTS`), overridable via `config/praxis.yaml`

## Skill system

Spec: `docs/architecture/skill-system.md`. Round-trip integrity, write gate (`authorize_write`),
schema gate, DAG acyclicity, shared principles in `config/skills/_shared/principles.md`.

## Memory system (R1–R4 + side-channels)

Spec: `docs/architecture/l3-memory.md`. Four operational rings (R1 working→R2 short→R3 long→R4
archive); R5 graph defaults OFF; bypass side-channels (Mer/R5/User Profile) degrade to no-ops on error.

## Security posture & harness

Spec: `docs/architecture/security-evidence.md`. Modes: `productive` (default) | `security-test`
(attack). Harness modes: `governed|code|semi|minimal`. Every mode change records evidence.

## Comment conventions

- **English baseline** for all comments/docstrings — CJK only in intentional data (i18n, injection keywords)
- **Module docstring required** for every module; **class docstring required** for every public class;
  **public function docstring required** (simple getters/setters/private helpers exempt)
- Style: triple-double-quoted, first line = short imperative; Args/Returns only when non-obvious

## Commit conventions (enforced by `.githooks/commit-msg`)

Full spec: `docs/workflow/commits.md`. Load-bearing summary:

- **English + Conventional Commits** `type(scope): summary` ≤ 72 chars, lowercase start, imperative mood present-tense verb (no past tense / gerunds), no markdown, no trailing period
- **Exactly ONE `Co-Authored-By:` trailer** strictly last line, preceded by a blank line (no trailing notes):
  `Co-Authored-By: <registered-agent> (<detected-model>) <noreply@domain>`
- **Attribution verified for TRUTH (Anti-Impersonation Rule)**: cross-checked against agents registry + live execution evidence
  (`check_attribution.py` reads the harness session log — unfakeable); model claims without proof are rejected.
  Agents MUST probe runtime first (`python scripts/py/check_attribution.py --json`) and MUST NEVER arbitrarily grab
  registered identities from `commits.yaml`. If unregistered or unverifiable, the agent MUST notify the user
  for registry addition or environment pinning (`PRAXIS_AUTHOR`/`PRAXIS_MODEL`).
- **Single source of truth**: `config/discovery/commits.yaml` is canonical;
  `scripts/py/gen_commits_json.py` refreshes the Node-only `config/discovery/commits.json` mirror used by
  the commit hook
- **CompletionJudge decides "done"**: `bash scripts/sh/gate-merge.sh completion` (11 dimensions) — only
  COMPLETE authorizes done
- **Mainline net-delta gate**: ≥ 1000 net code, three locks (comment stripping / symmetric deletion / hygiene ceiling)

## Branching workflow (see `docs/workflow/branching.md`)

- Feature branches only (`feature/*`); merge with `--no-ff` after double-green
- **Local-merge gate**: `bash scripts/sh/gate-merge.sh local` before merging into local main
- **Sensitive-path hunk gate**: merge gates audit `docs/roadmaps/` and `config/discovery/`; opaque
  full-file replacements and deletions fail closed for review
- **Branch accumulation quality gate**: ≥ 5 unmerged commits AND ≥ 4000 net lines vs main → BLOCKED
  until review clears
- **Parallel collaboration**: one agent per domain, one worktree per agent, merge order K→M/T/S→C/B→A
- **Shared handoff area**: read `docs/agent-handoff/ALIGNMENT.md` before committing and register
  shared-file changes there — never clobber another agent's merged work (see clobber warning)
- **Shared-file gate (STRICT)**: commits touching `scripts/sh/`, `.githooks/`, `config/discovery/` MUST
  register in `docs/agent-handoff/ALIGNMENT.md` in the SAME commit — `commit-msg` rejects otherwise;
  when push-both reports the handoff area grew past `HANDOFF_LOG_MAX` (30), run
  `bash scripts/sh/handoff-rotate.sh` to archive old entries

## Build environment code of conduct

Spec: `docs/workflow/code-of-conduct.md`. Load-bearing rules:

- **Worktree gate**: never edit `systems/python-reference-runtime/ tests/ config/ scripts/ docs/` on main tree — build in a worktree
- **Two independent waivers** (user-granted, never self-awarded, never conflated): (1) Main-tree
  modification waiver (WHERE); (2) Branch pre-merge waiver (WHEN — `MERGE_GATE_SKIP=1` +
  `MERGE_GATE_REASON`)
- **Worktree venv**: no `.venv/` — always target main tree's `.venv`
- **Architecture doc sync**: architecture-level changes update the doc in the same commit
- **Definition of done**: CompletionJudge COMPLETE + worktree clean + docs synced + gates green + push plan set

## Contract versioning

- API routes under `/api/v2/`; breaking changes need `/api/v3/` + manifest entry
- Version bumps atomic: `pyproject.toml` + AGENTS.md header + `KERNEL_VERSION` + tests + docs in ONE commit

## Lint / format / typecheck

```bash
make test|test-extended|test-all     # test batches (runner.py)
make lint|format|typecheck|coverage  # static gates
make precommit                       # pre-commit hooks (ruff + size + mainline whitelist)
make hooks                           # git config core.hooksPath .githooks
make push-both                       # git push origin main; git push github main
make bump-version                    # atomic version bump
```

Hook systems: `.githooks/` (bash: pre-commit/commit-msg/post-checkout — load-bearing governance gates)
vs `.pre-commit-config.yaml` (style lint only, not governance).

## Testing quirks

- Singleton pollution: `tests/conftest.py` resets all registered singletons before each test; add new
  services to `_RESETS`
- Layer import test (`test_layer_imports.py`) checks all `.py` files; new cross-layer imports must be allowlisted
- `pyproject.toml` sets `addopts = "-n auto --dist loadfile"` for parallel pytest; `-n 0` pins in CI
  are explicit overrides

## Key files

`systems/python-reference-runtime/main.py` — CLI entry | `systems/python-reference-runtime/l5/cli.py` — CLI commands | `systems/python-reference-runtime/l1/kernel/os.py` — OS lifecycle |
`systems/python-reference-runtime/l1/kernel/constitution.py` — Constitutional rules engine |
`systems/python-reference-runtime/l3/tool_system/tool_pipeline.py` — 9-step execution pipeline |
`systems/python-reference-runtime/l3/card/card_registry.py` — Card lifecycle | `systems/python-reference-runtime/l3/boot/boot.py` — 7-step bootstrap |
`systems/python-reference-runtime/l3/cell/peers/l3a/` — L3A session system (25 modules) | `systems/python-reference-runtime/l3/cell/peers/l3.py` — CentralController

## Project structure & sandbox

Layout: `docs/project-structure.md`. Sandbox/Diff: `docs/architecture/sandbox-diff.md`.
