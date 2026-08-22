# Alignment State — live

> Updated whenever an agent registers a shared-file change or a merge lands.
> Read before committing; append before pushing (see `README.md` rules).

## Active worktrees (2026-08-22)

| Worktree | Branch | Domain | Notes |
|---|---|---|---|
| praxis (main) | main | — | stable |
| praxis-kernel-next | root-kernel-next | K kernel | active |
| praxis-kernel-merge | root-kernel-converge | K kernel | active |
| praxis-kernel-preflight | root-kernel-preflight | K kernel | 170 commits ahead |
| praxis-session-id | s-session-identity | S sessions | active |
| praxis-gate-hardening-r2 | gate-hardening-r2 | infra | active |
| praxis-test-perf | test-perf-slicing | infra | active |
| praxis-coverage-wsl | coverage-wsl | infra | WSL judge coverage (AtomCode) |

## Shared-file change log

| Date | File | Agent | Change | Status |
|---|---|---|---|---|
| 2026-08-22 | scripts/sh/verify-completion.sh | GPT (infra merge) | ⚠️ CLOBBERED AtomCode's WSL-slice + dedupe optimization (f5087549/bb18759c) | reconciled — restored by AtomCode in coverage-wsl bd800342 |
| 2026-08-22 | scripts/sh/verify-completion.sh | AtomCode | coverage WSL serial (XDIST_ARGS) | in coverage-wsl bd800342 |
| 2026-08-22 | .githooks/commit-msg + scripts/sh/push-both.sh | AtomCode | shared-file handoff gate (strict register-or-reject) | in agent-handoff (this commit) |
| 2026-08-22 | scripts/sh/handoff-rotate.sh + push-both.sh | AtomCode | handoff-area growth check (threshold archive) | in agent-handoff (this commit) |

## Clobber warnings (do not repeat)

1. `verify-completion.sh` (2026-08-22): an infra merge overwrote an
   already-merged optimization. Before an infra/refactor merge touches a
   shared script, check `git log --oneline <file>` and rebase on existing
   optimization history instead of clobbering it.
