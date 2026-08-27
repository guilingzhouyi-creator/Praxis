# Agent Handoff — Shared Information Exchange

> 共享信息交接区：并行 Agent 对齐报告的统一存放处。
> All collaborators (humans + agent tools) MUST read `ALIGNMENT.md` before
> committing and register shared-file changes here (see
> `docs/workflow/collaboration.md` §2 boundary rule + §4 shared-file register).

## Why

Parallel agents (k/m/s/t/c/b/a + tool/infra agents) share one repo. Without a
shared exchange area, merges clobber each other's work — e.g. 2026-08-22 the
judge `gate-merge.sh completion` WSL-slice optimization was silently overwritten by
an unrelated infra merge (see `ALIGNMENT.md` "Clobber warnings").

## Rules

- **Before committing**: read `ALIGNMENT.md` — if shared files of your domain
  (`scripts/sh/`, `.githooks/`, `config/discovery/`, `docs/`) were touched by
  another agent, reconcile first.
- **Register shared-file changes**: when you modify a file outside your owned
  domain, append a line to `ALIGNMENT.md` "Shared-file change log" BEFORE
  pushing — a one-line entry with date/file/agent/change.
- **One worktree per branch**: `git worktree add ../praxis-<area>
  feature/<agent>-<area>`; never commit in another agent's worktree.
- **Do not silently overwrite**: an infra/refactor merge that touches a shared
  script must check `git log --oneline <shared-file>` first — if the file has
  un-merged optimization history, rebase on it instead of clobbering.

## Files

| File | Purpose |
|---|---|
| `ALIGNMENT.md` | Live alignment state: active worktrees, domain ownership, shared-file change log, clobber warnings |
| per-domain reports | Domain closure / handoff reports (e.g. `docs/roadmaps/l2-agent-handoff.md`) |
