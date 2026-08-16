# Praxis Documentation

Five-layer Agent OS. This index is the entry point for the docs tree:
architecture reference, configuration, workflows, design records, roadmaps,
and governance. The load-bearing rules live in `AGENTS.md` (source of truth);
this tree carries the detail.

## Layout

| Path | Contents | Language |
|---|---|---|
| [architecture/](architecture/README.md) | Layer reference L1–L5, cross-cutting, skill system, security, sandbox-diff — entry: `README.md` | EN |
| [configuration/](configuration/overview.md) | Three-layer configuration system overview | EN |
| [workflow/](workflow/branching.md) | Branching + parallel collaboration discipline (companion to `AGENTS.md`) | EN |
| [design/](design/) | Active design docs (`praxis-*`), `reviews/` (recent audits) | mixed |
| [design/archive/](design/archive/) | Closed-out reviews and design snapshots — **intentionally untracked** (see Maintenance rules) | mixed |
| [decisions/](decisions/) | Historical MVP / tech-stack decision records | zh |
| [roadmaps/](roadmaps/README.md) | Centralized roadmap index — entry: `README.md` | zh |
| [notes/](notes/) | Personal notes (cognitive formula; `随笔/` not tracked) | zh |
| [issues/](issues/TEMPLATE.md) | Issue specification template | EN |
| [judge-stats.md](judge-stats.md) | CompletionJudge effectiveness dashboard — **auto-updated**, never hand-edit | EN |

## Reading paths

- **New to Praxis**: `architecture/README.md` → `configuration/overview.md` → `workflow/branching.md`
- **Contributing**: `AGENTS.md` (load-bearing rules) → `workflow/*` → the per-subsystem doc linked from `AGENTS.md`
- **Maintaining docs**: run `make doc-stats` before merging any architecture-level change

## Maintenance rules

- **Numbers are generated** — `make doc-stats` (`gen_doc_stats.py` +
  `check_doc_stats.py --fix` + `gen_llms_txt.py`) refreshes the statistics
  snapshot in `architecture/README.md`, `llms.txt` and `llms-full.txt`.
  Never hand-edit those numbers; `check_doc_stats.py` drift-gates them in CI.
- **Archive contract** — `docs/design/archive/` and `docs/notes/随笔/` are
  intentionally **untracked** (`.gitignore`, commit `f21dbbd`). Moving a file
  there removes it from git: content survives only on the main-tree disk and in
  deletion-commit history (`git log --all --diff-filter=D`). Review the
  contract before relying on archived docs in worktrees or CI.
- **Docs travel with code** — architecture-level changes ship their
  `docs/architecture/` update in the same commit (see `AGENTS.md` build
  environment code of conduct).
- **Language** — architecture / configuration / workflow in English;
  roadmaps / design / decisions in Chinese (project convention).
