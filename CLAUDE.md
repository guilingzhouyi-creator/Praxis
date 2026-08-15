# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## AGENTS.md is the source of truth

`AGENTS.md` carries the full, load-bearing rule set — conventions, security
posture, memory/skill systems, commit/branch/merge gates, contract versioning.
**This file is only a thin Claude-Code-facing pointer; it does not restate those
rules.** Before touching a subsystem, read the relevant `AGENTS.md` section and
the `docs/architecture/*.md` it links.

## Orientation

Praxis is **not a game** — it is a five-layer Agent OS (Python 3.11+) that maps
OS concepts onto LLM agents. Two overloaded terms:
- **Card** = the unit of work (process control block): `submit → approve →
  execute → complete`.
- **Cell** = the scheduling unit (CPU core): holds N `AgentTerminal` thread
  pools, routes Cards by territory.

Layers (`src/`): **L5** user CLI → **L4** bridge (API `/api/v2/`, LLM, sandbox,
MCP) → **L3** cell (agents, 4-ring memory, cards, tool pipeline) → **L2** shell
(YAML commands + i18n) → **L1** kernel (constitution, gatechain, VFS, `params/`,
`ports/`). Import direction is enforced (L5→…→L1, never upward) by
`tests/infra/test_layer_imports.py`.

## Commands (full lists: AGENTS.md "Test commands" / "Lint / format / typecheck")

Run inside **WSL** with the repo venv — a Windows `python.exe` lacks xdist/mypy
and is not valid. `source .venv/bin/activate` or prefix `.venv/bin/python`.

```bash
pip install -e ".[test]"
python src/main.py boot|health|status          # boot / self-test / status
python -m l2.l2_shell                           # interactive shell
python -m pytest tests/l1/test_kernel.py -x -q  # single file
python tests/runner.py --batch 1|2              # fast | slow batch
make test | lint | format | typecheck | coverage
```

## Before changing code — read these AGENTS.md sections

- **Build environment code of conduct** — worktree gate: never edit
  `src/ tests/ config/ scripts/ docs/` on the main tree; a worktree has no venv
  of its own (target the main tree's `.venv`).
- **Key conventions** — magic numbers → `params/`; prompts are data
  (`prompts.py`, not inlined `system=`); English-only comments.
- **Commit / branch / merge** — Conventional Commits + exactly one
  `Co-Authored-By` trailer; dual-remote `push-both.sh` (origin first); the
  mainline net-delta gate; `verify-completion.sh` decides "done".

## LLM config

Default `ollama` / `codellama:7b` at `localhost:11434`; override via
`config/praxis.yaml` or env (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`,
`ANTHROPIC_API_KEY`, `OLLAMA_URL`).
