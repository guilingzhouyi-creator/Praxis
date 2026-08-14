---
name: git-workflow
description: Use when committing, merging, branching, or pushing in the Praxis repo — dual-remote pushes, GPG signing, worktree discipline, hook gates (mainline whitelist, commit-msg rules, dependabot merge gate), and the double-green merge rule.
---

## Overview

Checklist for the Praxis git governance process. AGENTS.md (`## Remote strategy`, `## Branching workflow`, `#### Two hook systems`) is the authoritative reference; this skill is the condensed operational order. Follow it on every commit/merge/push.

## Before Any Branch Switch

- Run `bash scripts/sh/check-worktree.sh` first — it rejects a dirty tree (exit 1) and duplicate checkouts of the same branch (exit 2). Never switch with a dirty tree; commit, stash, or commit as WIP first.
- If dirty changes are found on the wrong branch, `git checkout <their-branch>` so they follow back home, then commit/stash.
- Treat `.githooks/post-checkout` warnings as violation reports, not annoyances.
- Check `git stash list` after interrupted commands (killed shells skip `git stash pop`).

## Worktree Discipline (Parallel Agents)

- One working tree per agent: `git worktree add <path> feature/<agent>-<area>`. Sharing one tree across branches is FORBIDDEN — uncommitted changes follow `git checkout` and silently pollute the other branch.
- Clean up after merging: `git worktree remove <path>`; `git worktree list` shows all checkouts.

## Feature Branch Workflow

- Open `feature/*` branches for multi-Phase features, shared-module refactors, risky changes, parallel work.
- Semi-finished work never enters mainline — commit it or branch it.
- **Double-green merge rule**: feature branch tests pass AND main tests pass → merge with `--no-ff`. Discard = proposal rejected.
- **Keep merged branches** for traceability — never delete them after merge; recover deleted ones with `git branch <name> <tip-sha>`.

## Hook Gates (What Will Reject a Commit)

- **Pre-commit** (`.githooks/pre-commit`) runs on STAGED `.py` files only:
  - `ruff check --fix` aborts with `--exit-non-zero-on-fix` when it auto-fixes — re-stage and retry.
  - `ruff format --check` rejects unformatted files — run `ruff format <files>` before staging.
  - Size check (`scripts/py/pre-commit-size-check`): bulk commits >10k lines need `SKIP_SIZE_CHECK=1`.
  - **Mainline whitelist gate**: only `docs/ config/ locales/ .githooks/ scripts/` etc. may commit directly on main; in-progress merges are exempt (the sanctioned double-green path). Governance files (`AGENTS.md`, `.github/`) are NOT whitelisted — land them via feature branch or `--no-verify`.
- **Commit-msg** (`.githooks/commit-msg`):
  - Messages MUST be English (CJK rejected).
  - MUST carry a `Co-Authored-By` trailer: `Co-Authored-By: OpenCode (deepseek-v4-flash) <noreply@opencode.ai>`.
  - Merge/Revert commits are exempt (use git's default `Merge ...`/`Revert ...` message — a hand-typed lowercase `merge:` gets full checks).
  - Dependabot merge gate reads `.git/MERGE_HEAD` — see the dependabot-merge skill.

## Push Discipline

- Dual remotes: `origin` = GitCode (canonical), `github` = GitHub mirror (CI carrier). **Every push to main goes to BOTH**: `bash scripts/sh/push-both.sh main` (or `make push-both`). Pushing only to GitCode silently skips CI.
- GPG signing is mandatory for main (repo `commit.gpgsign=true`); if a local override disables it, the push is rejected — fix before pushing.
- Never `git merge --no-verify` / `git commit --no-verify` or `PRAXIS_SKIP_AUTHOR_CHECK=1` except for broken-hook recovery; a `--no-verify` dependabot merge requires second-agent review before push.

## Domain Partition

- 7 work domains: K kernel / M memory / S sessions / T tools / C card-cell / B bus-services / A bridge-shell. Each agent owns exactly one domain; announce before touching another.
- Shared files register (one writer at a time): `l3.py`, `params/*.py`, `l3/boot/`, `tests/conftest.py`, `test_layer_imports.py`, `config/praxis.yaml`. Cross-domain API additions commit to main first.
- Merge order: K → M/T/S → C/B → A.
