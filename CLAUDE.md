# CLAUDE.md

Thin Claude-Code-facing pointer to the full governance index (`AGENTS.md`).
**Before touching any subsystem, read the relevant AGENTS.md section and the doc it links.**

## AGENTS.md is the source of truth

`AGENTS.md` carries the full load-bearing rule set + a doc index pointing at
`docs/architecture/*.md`, `docs/workflow/*.md`, `docs/project-structure.md`.
**This file does not restate those rules.**

## Orientation

Praxis is a five-layer Agent OS (Python 3.11+): L5 CLI → L4 Bridge → L3 Cell → L2 Shell → L1 Kernel.
Card = unit of work. Cell = scheduling unit. Import direction enforced downward.

## Commands

Run inside WSL with the repo venv (`.venv/bin/python`). Quickstart:
`pip install -e ".[test]"` → `python src/main.py boot|health|status|ps|card` → `python -m pytest tests/ -x -q`.
Full lists: AGENTS.md "Test commands" / "Lint / format / typecheck".

## Before changing code — mandatory gates

See `docs/workflow/code-of-conduct.md` for full text. Key rules:
- **Worktree gate**: never edit `src/ tests/ config/ scripts/ docs/` on main tree
- **Two independent waivers** (user-granted, never self-awarded): main-tree modification (WHERE)
  and branch pre-merge (WHEN)
- **Key conventions**: magic numbers → `params/`; prompts are data; English-only comments
- **Commit / branch / merge**: Conventional Commits + Co-Authored-By; dual-remote push;
  `verify-completion.sh` decides "done"
- **Shared handoff area** (`docs/agent-handoff/`): read `ALIGNMENT.md` before committing; shared-file
  changes (`scripts/sh/`, `.githooks/`, `config/discovery/`) must register there in the SAME commit —
  `commit-msg` rejects otherwise (AGENTS.md "Shared-file gate (STRICT)")

## LLM config

Default: `ollama` / `codellama:7b` at `localhost:11434`. Override via `config/praxis.yaml` or env vars.