# Build Environment Code of Conduct (构建环境守则)

Non-negotiable build discipline. Full procedures live in
`docs/workflow/branching.md` and `docs/workflow/collaboration.md`; the rules
below are the load-bearing summary, stated here exactly once (index into
`AGENTS.md` `## Key conventions` / `## Contract versioning` /
`## Project structure` for the referenced details).

## Worktree gate — mandatory before ANY code change

NEVER edit `src/`, `tests/`, `config/`, `scripts/`, or `docs/` on the main
tree. Plan first, then build in a dedicated worktree:
`git worktree add ../praxis-<area> feature/<agent>-<area>`.

ALWAYS run `bash scripts/sh/check-worktree.sh` (exit 0 required) before any
`git checkout`/`git switch` on a shared tree. The main tree only receives
merges; never leave uncommitted changes on it. A plan comes before the branch;
the branch comes before the edit. (Per-agent multi-tree: `AGENTS.md`
`## Parallel collaboration`.)

## Gate waivers — TWO independent exemptions (do not conflate)

The gate system has exactly two waivers, each granted by the user, never
self-awarded:

1. **Main-tree modification waiver (主树修改推进豁免)** — grants permission
   to EDIT ON the main tree paths (`src/` `tests/` `config/` `scripts/`
   `docs/`) instead of opening a worktree. It waives WHERE you change code,
   NOT whether the change may ship. Default: DENIED (worktree gate above).
   Grant signal: user approves "准许主树操作 / allowed to edit on main".
2. **Branch pre-merge waiver (分支提前合入门禁豁免)** — grants permission to
   MERGE a branch into `main` before it meets the net-delta gate (≥ 1000).
   It waives WHEN a branch may merge, NOT where you edit. Default: DENIED —
   branches MUST reach the gate to keep mainline lean; merging early is
   exactly what the gate prevents. Grant signal: user approves
   `MERGE_GATE_SKIP=1` (with `MERGE_GATE_REASON`).

Neither waiver permits pushing to remotes by itself — pushing is governed by
`push-both.sh` (dual remotes) and the mainline gate; a waiver only relaxes
its own dimension (where-to-edit / when-to-merge). Never treat "allowed to
edit on main" as "allowed to merge early", or vice versa.

## Worktree venv — no isolated environment

A worktree is a separate checkout and has NO `.venv/` of its own — the repo
venv lives only on the main tree. Tests, hooks, and scripts run inside a
worktree MUST target the main tree's venv: activate it first
(`source <main-tree>/.venv/bin/activate`) or prefix every command with its
absolute path (e.g. `<main-tree>/.venv/bin/python -m pytest ...`). Never call
a bare `python` or a worktree-local `.venv/bin/python` from inside a worktree
— `python: command not found` (pre-commit/commit-msg hooks,
`verify-completion.sh`) and `.venv/bin/python: No such file or directory`
(pytest) are the two symptoms of this exact mistake.

## Architecture doc sync — mandatory with architecture-level changes

Any architecture-level adjustment (new layer/module/service, changed
contract, renamed subsystem, moved path, new parameter domain) MUST update
the corresponding `docs/architecture/` doc IN THE SAME COMMIT as the code
change — a code change never ships without its doc. Reuse the normalized
layout of `docs/architecture/README.md` (`# Title` + one-line summary +
optional `mermaid` + inventory/contract tables); never invent a parallel
layout.

## Generated numbers — never hand-edit

Refresh counts with `make doc-stats` (`scripts/py/gen_doc_stats.py`);
`scripts/py/check_doc_stats.py` drift-gates them in CI. Register every new
subsystem doc in AGENTS.md AND in the `docs/architecture/README.md` layer
list. Doc prose in English (per `AGENTS.md` `## Comment conventions`);
first-line summary + tables for structured data.

## Naming discipline — no ad-hoc names

New identifiers (modules, params, config keys, API segments, directory
names) MUST follow the conventions registered in `AGENTS.md`
`## Key conventions`, `## Contract versioning`, and `docs/project-structure.md`
(目录命名规则). Register a genuinely new name class in the docs (and
`params/` where applicable) FIRST — never introduce one silently.

## Definition of done (before merge)

A change is merge-ready only when ALL hold:

- **Machine verdict first**: `bash scripts/sh/verify-completion.sh` reports
  `COMPLETE` (11-dimension gate; `INCOMPLETE` → keep working, do NOT declare
  done). This is the machine's answer to "is it really finished?".
- **Worktree clean**: branch committed, no in-flight edits on main
  (`scripts/sh/check-worktree.sh` exit 0 before any switch).
- **Docs synced**: architecture-level changes ship with their
  `docs/architecture/` update in the same commit.
- **Gates green**: layer-import + params-compliance + domain tests +
  full baseline + ruff, all passing.
- **Push plan set**: after merge, `bash scripts/sh/push-both.sh main`
  (dual remotes — never push to GitCode only).
