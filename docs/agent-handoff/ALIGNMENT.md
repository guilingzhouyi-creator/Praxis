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
| praxis-hooks-strict | hooks-strict | infra | strict commit-msg worktree enforcement |

## Shared-file change log

| Date | File | Agent | Change | Status |
|---|---|---|---|---|
| 2026-08-22 | scripts/sh/verify-completion.sh | GPT (infra merge) | ⚠️ CLOBBERED AtomCode's WSL-slice + dedupe optimization (f5087549/bb18759c) | reconciled — restored by AtomCode in coverage-wsl bd800342 |
| 2026-08-22 | scripts/sh/verify-completion.sh | AtomCode | coverage WSL serial (XDIST_ARGS) | in coverage-wsl bd800342 |
| 2026-08-22 | .githooks/commit-msg + scripts/sh/push-both.sh | AtomCode | shared-file handoff gate (strict register-or-reject) | in agent-handoff (this commit) |
| 2026-08-22 | scripts/sh/handoff-rotate.sh + push-both.sh | AtomCode | handoff-area growth check (threshold archive) | in agent-handoff (this commit) |
| 2026-08-22 | config/discovery/commits.yaml | OpenCode (l3-normalize) | registered `services` scope + scope_dirs entry (46-file dir had none; exposed by slice B1) | reconciled retro-registry |
| 2026-08-22 | scripts/sh/verify-completion.sh + judge-stats.sh + verify-local-merge.sh | AtomCode | judge test-skip visibility (skipped_tests record + dashboard + merge notice) | in judge-tests-gate (this commit) |
| 2026-08-22 | .githooks/commit-msg + Makefile + .githooks/commit-template.txt + .github/workflows/commit-lint.yml | OpenCode | strict commit-msg: enforce executable, absolute hooksPath, bypass audit, worktree CI gate | in hooks-strict (this commit) |
| 2026-08-22 | scripts/sh/ensure-hooks.sh + scripts/py/commit_strict.py + tests/infra/*hook* | OpenCode | worktree inheritance enforcer and strict hook tests | in hooks-strict (this commit) |
| 2026-08-22 | .githooks/commit-msg + scripts/sh/* + scripts/js/validate-commit.mjs + scripts/py/gen_commits_json.py + config/discovery/commits.json | AtomCode | test-suite hardening (must_include regression + judge/rotate tests) + set -euo + Node validator restore + commits.json regen | in opt-hardening (this commit) |
| 2026-08-22 | config/discovery/commits.yaml + commits.json + scripts/py/commit_scan.py + gen_commits_json.py + scripts/js/validate-commit.mjs + scripts/sh/* | AtomCode | single-source type-content rules + set-flag cleanup | in opt-hardening (this commit) |
| 2026-08-23 | scripts/py/audit_merge_hunks.py + tests/infra/test_merge_hunks.py + AGENTS.md + docs/workflow/* | GPT (root-kernel-next) | fail closed on sensitive-file deletions and multi-hunk full replacements; record incident regression | in feature/root-kernel-next |
| 2026-08-23 | crates/l1-kernel-rs/src/process_group.rs + crates/l1-kernel-rs/tests/process_group.rs + docs/architecture/* + docs/roadmaps/frontend-kernel-roadmap.md | GPT (root-kernel-next) | bounded reaper plan selection copies at most max_members handles per sweep; independent regression covers multi-group budget accounting | in feature/root-kernel-next |
| 2026-08-23 | crates/l1-kernel-rs/src/benchmark_runner.rs + crates/l1-kernel-rs/tests/benchmark_runner.rs + docs/architecture/l1-kernel.md + docs/roadmaps/frontend-kernel-roadmap.md | GPT (root-kernel-next) | process.group.reaper benchmark now forces 64-member multi-sweep progress so the bounded-selection optimization is measured | in feature/root-kernel-next |
| 2026-08-23 | crates/l1-kernel-rs/src/process_group.rs + benchmark_runner.rs + src/bin/rust-process-group-bench.rs + crates/l1-kernel-rs/tests/* + docs/architecture/* + docs/roadmaps/frontend-kernel-roadmap.md | GPT (root-kernel-next) | terminal-member counter, snapshot-free reaper fast path, isolated process.group.reaper v3 evidence | in feature/root-kernel-next |
| 2026-08-23 | docs/workflow/commits.md + tests/infra/test_config_consistency.py | GPT (root-kernel-next) | remove stale absent-generator claim and lock the checked-in JSON mirror contract | in feature/root-kernel-next |
| 2026-08-23 | crates/l1-kernel-rs/src/registry_base.rs + benchmark_runner.rs + src/bin/rust-registry-base-bench.rs + crates/l1-kernel-rs/tests/* + docs/architecture/* + docs/roadmaps/frontend-kernel-roadmap.md + Makefile | GPT (root-kernel-next) | hash-index registry lookup with stable order semantics and isolated registry.base.lookup v3 evidence | in feature/root-kernel-next |
| 2026-08-23 | docs/roadmaps/l2-ts-rewrite-mapping.md | GPT (root-kernel-next) | carry forward the latest main-tree TS mapping document so the merge audit does not treat it as a deletion | in feature/root-kernel-next |

## Clobber warnings (do not repeat)

1. `verify-completion.sh` (2026-08-22): an infra merge overwrote an
   already-merged optimization. Before an infra/refactor merge touches a
   shared script, check `git log --oneline <file>` and rebase on existing
   optimization history instead of clobbering it.
