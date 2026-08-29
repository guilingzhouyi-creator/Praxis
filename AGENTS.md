# Praxis — Agent OS (v0.4.2 "Aether")

Python 3.11+ Agent OS for orchestrating LLM-based agents. Five-layer architecture
from bare-metal kernel to user CLI. `CLAUDE.md` is the thin Claude-Code pointer to
this file; `docs/workflow/README.md` is the employee-handbook index.

## Doc libraries — QUERY FIRST, then act

Four libraries carry the norms. **When a normative question is unclear, search the
libraries before acting; if the answer is not there, ask the user. Never "fix" a
norm from memory.**

| Library | Index | Holds |
|---|---|---|
| Employee handbook (员工手册库) | `docs/workflow/README.md` | commits / branching / collaboration / code-of-conduct — the operational norms |
| Archive (归档库) | `docs/design/README.md` + `POINTERS.json` | design + review + roadmap records; `construction: closed` → auto-archived via `docs/design/_outgoing/` |
| Roadmaps (路线图库) | `docs/roadmaps/README.md` | direction & phases; `ROADMAP-*` pointers, `construction: planned\|in_progress\|closed` |
| Architecture | `docs/architecture/README.md` | layer map, contracts, per-subsystem specs (memory / skill / security / sandbox / config / automation); repo layout & naming: `docs/project-structure.md` |

## Non-negotiable rules (imperative)

1. **WORKTREE GATE**: never edit `systems/python-reference-runtime/ tests/ config/ scripts/ docs/` on the main tree — build in a worktree. Waivers are USER-GRANTED, never self-awarded: (1) main-tree modification (WHERE), (2) branch pre-merge (WHEN, `MERGE_GATE_SKIP=1` + `MERGE_GATE_REASON`). Never conflate them.
2. **LAYER IMPORTS**: L5→L4→L3→L2→L1 only; L1 never imports upward; the three runtime systems never import each other. (Enforced: `tests/infra/test_layer_imports.py`, `make system-boundaries`.)
3. **CONSTANTS**: all magic numbers in `l1/kernel/params/`; new config items register defaults in `kernel/settings.py DEFAULTS`; new tools register via `ToolSpec` in `config/tools.yaml`; new kernel modules export in `kernel/__init__.py __all__`.
4. **LANGUAGE**: English comments/docstrings (CJK only in intentional data); module/class/public-function docstrings required; double quotes, line-length 120; no bare `except:`.
5. **COMMITS** (enforced by `.githooks/commit-msg`): English + Conventional Commits `type(scope): summary` ≤ 72 chars, imperative; exactly ONE `Co-Authored-By:` trailer as the last line. Attribution verified for TRUTH: probe `python scripts/py/check_attribution.py --json` first, never grab identities from `config/discovery/commits.yaml`; unverifiable → notify the user (registry addition or `PRAXIS_AUTHOR`/`PRAXIS_MODEL` pins).
6. **DONE = machine verdict**: `bash scripts/sh/gate-merge.sh completion` (11 dimensions) — only `COMPLETE` authorizes "done". Dashboard: `docs/judge-stats.md`.
7. **SHARED FILES**: commits touching `scripts/sh/`, `.githooks/`, `config/discovery/` MUST register in `docs/agent-handoff/ALIGNMENT.md` in the SAME commit (commit-msg rejects otherwise).
8. **MERGE**: feature branch + double-green + `--no-ff`; run `bash scripts/sh/gate-merge.sh local` before merging; mainline net-delta ≥ 1000 (three locks); waivers are the user's decision only.
9. **PUSH**: `bash scripts/sh/push-both.sh main` — BOTH remotes (origin=GitCode first, then github mirror).
10. **DONE DEFINITION**: CompletionJudge COMPLETE + worktree clean + docs synced (architecture-level changes ship with their doc in the same commit) + gates green + push plan set.

## Quick start

```bash
pip install -e ".[test]"                       # install + dev deps
python systems/python-reference-runtime/main.py boot|health|status|ps|card  # kernel lifecycle + dispatch
python -m l2.l2_shell                          # interactive L2 Shell
```

## Commands

All commands inside the repo venv (`.venv/bin/python`).

```bash
python -m pytest tests/ -x -q                    # full suite
python tests/runner.py --batch 1|2               # batch splits
make lint|format|typecheck|coverage|precommit    # static gates
make hooks                                       # git config core.hooksPath .githooks
make push-both                                   # dual-remote push
make bump-version                                # atomic version bump
```

Hook systems: `.githooks/` (bash: pre-commit / commit-msg / post-checkout —
load-bearing governance gates) vs `.pre-commit-config.yaml` (style lint only).

## Architecture (layer map)

```
systems/python-reference-runtime/ — Python reference runtime (L5→L4→L3→L2→L1)
systems/rust-kernel-engine/       — independent Rust formal-kernel rewrite
systems/typescript-shell-engine/  — independent TS shell/protocol rewrite
tests/ + scripts/ + config/ + docs/ — build and verification perimeter only

l5/ User (cli.py, agent_runtime.py)
l4/ Bridge (API gateway, LLM engine+providers, sandbox, MCP, search, LSP, vault)
l3/ Cell (agents, memory, cards, scheduler, tool pipeline, discussion; peers/l3a session daemon, peers/l3.py CentralController)
l2/ Shell (shells/, l2_shell engine, protocol v1 wire contract)
l1/kernel/ (sync, event, constitution, allocator, gatechain, VFS, IPC, params/; ports/ = 18 *Port(ABC))
```

## Key files

`main.py` (CLI entry) · `l5/cli.py` · `l1/kernel/os.py` (OS lifecycle) ·
`l1/kernel/constitution.py` · `l3/tool_system/tool_pipeline.py` (9-step) ·
`l3/card/card_registry.py` · `l3/boot/boot.py` (7-step) ·
`l3/cell/peers/l3a/` (session system) · `l3/cell/peers/l3.py` (CentralController)

## Contract versioning

API routes under `/api/v2/`; breaking changes need `/api/v3/` + manifest entry.
Version bumps atomic: `pyproject.toml` + this header + `KERNEL_VERSION` + tests +
docs in ONE commit.

## Testing quirks

Singleton pollution → `tests/conftest.py _RESETS` (add new services there);
layer-import test allowlists new cross-layer imports; `pyproject.toml` sets
`addopts = "-n auto --dist loadfile"` (`-n 0` pins in CI are explicit overrides).
