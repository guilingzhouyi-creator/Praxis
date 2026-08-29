# CLAUDE.md

Thin Claude-Code-facing pointer to the governance libraries.
**Before touching any subsystem, read the relevant handbook page; query the
libraries on demand for unclear norms — never improvise.**

## Source of truth

`AGENTS.md` carries the non-negotiable imperative rules + the four-library map.
`docs/workflow/README.md` is the employee-handbook index (commits / branching /
collaboration / code-of-conduct). `docs/design/README.md` + `POINTERS.json` and
`docs/roadmaps/README.md` are the archive/roadmap libraries — query via their
indexes; unclear norm → search the libraries first, then ask the user.

## Orientation

Praxis is a five-layer Agent OS (Python 3.11+): L5 CLI → L4 Bridge → L3 Cell →
L2 Shell → L1 Kernel. Card = unit of work. Cell = scheduling unit. Import
direction enforced downward.

## Non-negotiables (see AGENTS.md — do not restate here)

- Worktree gate before ANY code change; waivers user-granted only
- Layer imports downward only; constants → `l1/kernel/params/`
- English commits + Conventional Commits + exactly ONE `Co-Authored-By:`
  trailer (attribution verified — probe `check_attribution.py --json` first)
- "Done" = `bash scripts/sh/gate-merge.sh completion` COMPLETE verdict
- Shared-file changes (`scripts/sh/`, `.githooks/`, `config/discovery/`) register
  in `docs/agent-handoff/ALIGNMENT.md` in the SAME commit
- Merge: feature branch + double-green + `--no-ff` + net-delta ≥ 1000
- Push: `bash scripts/sh/push-both.sh main` — BOTH remotes

## Commands

Run inside WSL with the repo venv (`.venv/bin/python`):
`pip install -e ".[test]"` →
`python systems/python-reference-runtime/main.py boot|health|status|ps|card` →
`python -m pytest tests/ -x -q`. Static gates: `make lint|format|typecheck|precommit`.

LLM provider/model live in `config/praxis.yaml` (`llm.provider` / `llm.model`) —
not hardcoded here.
