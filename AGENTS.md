# Praxis — Agent OS (v0.4.2 "Aether")

Python 3.11+ Agent OS for orchestrating LLM-based agents. Five-layer architecture from bare-metal kernel to user CLI.

> **This file is an index.** It carries the load-bearing rules every agent must
> obey and points to the detailed docs in `docs/` for everything else. Read the
> linked doc before touching the subsystem it describes. `CLAUDE.md` is a thin
> Claude-Code-facing pointer to this file — keep the rules here, not there.

## Doc index

| Area | Entry points |
|---|---|
| Architecture (layers, module maps, contracts) | `docs/architecture/README.md` + per-layer docs (linked in `## Architecture`) |
| Workflow — commits, gates, push | `docs/workflow/commits.md` |
| Workflow — branching, accumulation gate | `docs/workflow/branching.md` |
| Workflow — parallel agents | `docs/workflow/collaboration.md` |
| Build discipline — worktree, waivers, DoD | `docs/workflow/code-of-conduct.md` |
| Repo layout & naming rules | `docs/project-structure.md` |
| Config system | `docs/configuration/overview.md` |
| Automation perimeter | `docs/architecture/automation.md` |
| Memory / skill / security / sandbox specs | `docs/architecture/l3-memory.md`, `skill-system.md`, `security-evidence.md`, `sandbox-diff.md` |

## Quick start

```bash
pip install -e ".[test]"          # install + dev deps (always via .venv/bin/python)
python src/main.py boot|health|status|ps|card  # kernel lifecycle + dispatch
python -m l2.l2_shell             # interactive L2 Shell (package with __main__.py)
```

Worktrees reuse the main tree's `.venv` — never create `.venv/` inside a worktree; invoke `.venv/bin/python` from the main tree.

## Test commands

All python via `.venv/bin/python`. Prefer `tests/runner.py --slice`; `--batch` is legacy.

```bash
python -m pytest tests/l1/test_kernel.py -x -q          # single file
python -m pytest tests/ -x -q                            # full suite (uses -n auto --dist loadfile)
python tests/runner.py --list-slices                     # list slices
python tests/runner.py --slice l3-fast --no-xdist        # single slice, serial (WSL: xdist startup is slow)
python tests/runner.py --batch 1                         # legacy: all except l3-slow
python tests/runner.py --batch 2                         # legacy: l3-slow only
```

`make test` = batch 1 (all except `l3-slow`); `make test-extended` = batch 2 (`l3-slow` only); `make test-all` = all slices in dependency order `infra → l1 → l2 → l3-fast → l3-mid → l3-slow → l4-fast → l4-lsp → l5 → integration → benchmarks`.

Lint: `make lint` (`ruff check src/ tests/`), `make format` / `make format-check`, `make typecheck` (`mypy src/`).
Coverage: `make coverage` (fails under 60%, `--ignore=tests/benchmarks/bench_card.py`).
Gates: `make precommit` = `pre-commit run --all-files` (style only); governance gates are `.githooks/` (see below).

## Architecture

Layer map (details: `docs/architecture/README.md`):

```
src/l5/ — User layer: cli.py, agent_runtime.py
src/l4/ — Bridge: API gateway, LLM engine+providers, sandbox, MCP, search, LSP, vault
src/l3/ — Cell layer: agents, memory, cards, scheduler, tool pipeline, discussion
src/l3/cell/peers/l3a/ — L3A orchestration daemon: session system, subagent pool, context epoch
src/l3/cell/peers/l3.py — CentralController (L3A+L3B+CardRegistry)
src/l2/ — Shell family: shells/ dialect adapters, l2_shell engine, protocol v1 wire contract
src/l1/kernel/ — Kernel primitives: sync, event, constitution, allocator, gatechain, VFS, IPC, params/
src/l1/kernel/ports/ — Port(ABC) abstractions
```

### Import rules (enforced by `tests/infra/test_layer_imports.py`)

- L5→L4→L3→L2→L1 only; L1 cannot import upper layers; cross-layer imports require an entry in `ALLOWLIST` in that test file — add a line there when introducing a new import.

## Key conventions

- **All magic numbers in `src/l1/kernel/params/`** — never hardcode in implementation files
- **New kernel modules** exported in `kernel/__init__.py __all__`
- **New config items** register defaults in `kernel/settings.py DEFAULTS`
- **Use `threading.RLock`** for reentrant locks; plain `threading.Lock` for flat sections
- **Unified `trace_id`**: `get_trace_id`/`set_trace_id`/`trace_scope` in `src/l3/error_bus/core.py`
- **Never import `services/` inside `kernel/`**
- **Register tools** via `ToolSpec` in `config/tools.yaml`
- **No bare `except:`** — use `except Exception:`
- **Double quotes** for strings (ruff `quote-style = "double"`), line-length 120
- **Prompt templates are data** in `src/l1/kernel/prompts.py` (`_DEFAULTS`), overridable via `config/praxis.yaml`

## Skill system

Spec: `docs/architecture/skill-system.md`. Round-trip integrity, write gate (`authorize_write`), schema gate, DAG acyclicity, shared principles in `config/skills/_shared/principles.md`.

## Memory system (R1–R4 + side-channels)

Spec: `docs/architecture/l3-memory.md`. Four operational rings (R1 working→R2 short→R3 long→R4 archive); R5 graph defaults OFF; bypass side-channels (Mer/R5/User Profile) degrade to no-ops on error.

## Security posture & harness

Spec: `docs/architecture/security-evidence.md`. Modes: `productive` (default) | `security-test` (attack). Harness modes: `governed|code|semi|minimal`. Every mode change records evidence.

## Comment conventions

- **English baseline** for all comments/docstrings — CJK only in intentional data (i18n, injection keywords)
- **Module docstring required** for every module; **class docstring required** for every public class; **public function docstring required** (simple getters/setters/private helpers exempt)
- Style: triple-double-quoted, first line = short imperative; Args/Returns only when non-obvious

## Commit conventions (enforced by `.githooks/commit-msg`)

Full spec: `docs/workflow/commits.md`. Load-bearing summary:

- **English + Conventional Commits** `type(scope): summary` ≤ 72 chars, lowercase start, no markdown, no trailing period
- **Exactly ONE `Co-Authored-By:` trailer** last, preceded by blank line: `Co-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>`
- **Attribution verified for TRUTH**: cross-checked against agents registry + live execution evidence (`detect_agent.py` reads the harness session log — unfakeable); model claims without proof are rejected
- **Single source of truth**: `config/discovery/commits.yaml` consumed by every gate (`commit-msg`, `verify-pr-merge.sh`, `generate_changelog.py`, `pr-review.yml`)
- **CompletionJudge decides "done"**: `bash scripts/sh/verify-completion.sh` (11 dimensions) — only COMPLETE authorizes done
- **Mainline net-delta gate**: ≥ 1000 net code, three locks (comment stripping / symmetric deletion / hygiene ceiling)

## Branching workflow (see `docs/workflow/branching.md`)

- Feature branches only (`feature/*`); merge with `--no-ff` after double-green
- **Local-merge gate**: `bash scripts/sh/verify-local-merge.sh` before merging into local main
- **Branch accumulation quality gate**: ≥ 5 unmerged commits AND ≥ 4000 net lines vs main → BLOCKED until review clears
- **Parallel collaboration**: one agent per domain, one worktree per agent, merge order K→M/T/S→C/B→A

## Build environment code of conduct

Spec: `docs/workflow/code-of-conduct.md`. Load-bearing rules:

- **Worktree gate**: never edit `src/ tests/ config/ scripts/ docs/` on main tree — build in a worktree
- **Two independent waivers** (user-granted, never self-awarded, never conflated): (1) Main-tree modification waiver (WHERE); (2) Branch pre-merge waiver (WHEN — `MERGE_GATE_SKIP=1` + `MERGE_GATE_REASON`)
- **Worktree venv**: no `.venv/` — always target main tree's `.venv`
- **Architecture doc sync**: architecture-level changes update the doc in the same commit
- **Definition of done**: CompletionJudge COMPLETE + worktree clean + docs synced + gates green + push plan set

## Contract versioning

- API routes under `/api/v2/`; breaking changes need `/api/v3/` + manifest entry
- Version bumps atomic: `pyproject.toml` + AGENTS.md header + `KERNEL_VERSION` + tests + docs in ONE commit

## Lint / format / typecheck

```bash
make test|test-extended|test-all     # test batches (runner.py, see Test commands)
make lint|format|typecheck|coverage  # static gates (coverage fails < 60)
make precommit                       # style only: pre-commit run --all-files (ruff + mypy + gitleaks)
make hooks                           # git config core.hooksPath .githooks + chmod +x
make push-both                       # git push origin main; git push github main (origin=GitCode canonical)
make bump-version                    # atomic version bump
make doc-stats                       # regenerate README numbers + llms.txt + check doc-index/CHANGELOG
make language-check                  # ts-test + ts-typecheck + rust-test + rust-fmt-check + rust-clippy
```

Hook systems: `.githooks/` (bash: pre-commit/commit-msg/post-checkout — load-bearing governance gates, staged-scoped `ruff check --fix` aborts commit so re-stage, plus size check + snake_case guard for `scripts/py/*.py`) vs `.pre-commit-config.yaml` (style lint only, not governance). PR CI lints **changed files only**; full-tree `ruff check + format` runs in nightly — locally run `make lint` for full-tree. Hooks are silently skipped when not executable; WSL `core.filemode=false` hides chmod loss — re-run `make hooks` after clone/worktree creation. Nightly also gates mypy no-new-debt (baseline 0), import-cycle, mem-check, layer/perf quality baselines, and dual-remote sync.

## Testing quirks

- Singleton pollution: `tests/conftest.py` resets all registered singletons before each test; add new services to `_RESETS`
- Layer import test (`test_layer_imports.py`) checks all `.py` files; new cross-layer imports must be allowlisted in `ALLOWLIST`
- `pyproject.toml` sets `addopts = "-v --tb=short --strict-markers -W ignore::DeprecationWarning -n auto --dist loadfile"` for parallel pytest; `-n 0` pins in CI are explicit overrides; use `--no-xdist` locally under WSL
- `make coverage` ignores `tests/benchmarks/bench_card.py`; `make doc-stats` must run after code changes that affect file/constant/route counts or CI `doc-stats` fails

## Multi-language builds

- `crates/l1-kernel-rs` — contract-only Rust boundary for the L1 kernel migration (`crates/Cargo.toml` workspace, `description` in `crates/l1-kernel-rs/Cargo.toml`).
- `packages/protocol-ts` — read-only TypeScript parity mirror of the Python L2 protocol v1; consumes `tests/fixtures/protocol_v1_records.json`, owns no L2/L3A/AgentLoop state.
- Commands: `make ts-install` / `ts-test` / `ts-typecheck`, `make rust-test` / `rust-contract-test` / `rust-fmt-check` / `rust-clippy` / `rust-benchmark`, or `make language-check` for all. CI `.github/workflows/multilang.yml` is path-triggered (`crates/**`, `packages/protocol-ts/**`) and pins Node 24 + Rust 1.97.1.

## Key files

`src/main.py` — CLI entry | `src/l5/cli.py` — CLI commands | `src/l1/kernel/os.py` — OS lifecycle |
`src/l1/kernel/constitution.py` — Constitutional rules engine | `src/l3/tool_system/tool_pipeline.py` — 9-step execution pipeline |
`src/l3/card/card_registry.py` — Card lifecycle | `src/l3/boot/boot.py` — 7-step bootstrap |
`src/l3/cell/peers/l3a/` — L3A session system | `src/l3/cell/peers/l3.py` — CentralController

## Project structure & sandbox

Layout: `docs/project-structure.md`. Sandbox/Diff: `docs/architecture/sandbox-diff.md`.

## OpenCode config

`opencode.json` enables MCP servers: `serena` (code navigation, 120s timeout), `sqlite` (`memory_graph.db`), `context7` (remote), `github` (local `npx`); `docker` is disabled. Instructions are not delegated via `opencode.json` `instructions` — this file is the source of truth.
