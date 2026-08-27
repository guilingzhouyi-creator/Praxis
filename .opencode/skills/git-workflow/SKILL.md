---
name: git-workflow
description: Use when committing, merging, branching, or pushing in the Praxis repo — dual-remote pushes, GPG signing, worktree discipline, hook gates (mainline whitelist, commit-msg rules, dependabot merge gate), the CompletionJudge, the mainline net-delta gate, PR-merge verification, and the double-green merge rule.
---

## Overview

Checklist for the Praxis git governance process. AGENTS.md (`## Remote strategy`, `## Branching workflow`, `## Commit conventions`, `#### Two hook systems`) is the authoritative reference; this skill is the condensed operational order. Follow it on every commit/merge/push.

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
- A merge is merge-ready only when ALL hold: CompletionJudge `COMPLETE`, worktree clean, docs synced in the same commit, gates green (layer-import + params-compliance + full suite + ruff), push plan set.

## Hook Gates (What Will Reject a Commit)

- **Pre-commit** (`.githooks/pre-commit`) runs on STAGED `.py` files only:
  - `ruff check --fix` aborts with `--exit-non-zero-on-fix` when it auto-fixes — re-stage and retry.
  - `ruff format --check` rejects unformatted files — run `ruff format <files>` before staging.
  - Size check (`scripts/py/check_commit_size.py`): bulk commits >10k lines need `SKIP_SIZE_CHECK=1`.
  - **Mainline whitelist gate**: only `docs/ config/ locales/ .githooks/ scripts/ README.md .pre-commit-config.yaml .praxis-rules.md` etc. may commit directly on main; in-progress merges are exempt (the sanctioned double-green path). Governance files (`AGENTS.md`, `.github/`, `.opencode/`, `.atomcode/`) are NOT whitelisted — land them via feature branch or `--no-verify`.
- **Commit-msg** (`.githooks/commit-msg`):
  - Messages MUST be English (CJK rejected).
  - MUST carry exactly ONE `Co-Authored-By` trailer, last line, preceded by a blank line:
    `Co-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>`
    (historical commits used `OpenCode (deepseek-v4-flash) <noreply@opencode.ai>`). No multi-agent stacking; noreply address required.
  - Subject: Conventional Commits `type(scope): summary`, ≤ 72 chars, imperative mood. Body after a blank line, structured Markdown (`## Sections`, **keywords**, `` `files` ``, `-` bullets).
  - Merge/Revert commits are exempt (use git's default `Merge ...`/`Revert ...` message — a hand-typed lowercase `merge:` gets full checks).
  - Dependabot merge gate reads `.git/MERGE_HEAD` — see the dependabot-merge skill.

## CompletionJudge & Net-Delta Gate

- **Declaration of done**: run `bash scripts/sh/gate-merge.sh completion` before declaring any task complete — only a `COMPLETE` verdict authorizes "done". Full 11-dimension breakdown: see the **completion-judge** skill.
- **Mainline merges**: `gate-merge.sh mainline` (auto-run by `push-both.sh main`) gates the net code delta with three locks (comment stripping / symmetric deletion / hygiene ceiling). Thresholds + mandatory post-rejection behavior: see the **net-delta-gate** skill.

## Push Discipline

- Dual remotes: `origin` = GitCode (canonical, stricter gate), `github` = GitHub mirror (CI carrier). **Every push to main goes to BOTH — push origin FIRST**: a GitCode rejection surfaces before anything is published on the mirror. Use `bash scripts/sh/push-both.sh main` (or `make push-both`). Pushing only to GitCode silently skips CI.
- `push-both.sh main` additionally: auto-refreshes doc-stats (`make doc-stats` + commits drift), records a CompletionJudge run (`--skip=tests,coverage`), and refreshes the judge dashboard (`docs/judge-stats.md`) — all auto-committed with `--no-verify` and the AtomCode trailer.
- GPG signing is OPTIONAL: the GitCode GPG-pre-receive hook is NOT enabled on this repository (commit `commit.gpgsign` off by default); signing is only required if that hook is later re-enabled. Keep signatures as normal hygiene when easy.
- Never `git merge --no-verify` / `git commit --no-verify` or `PRAXIS_SKIP_AUTHOR_CHECK=1` except for broken-hook recovery; a `--no-verify` dependabot merge requires second-agent review before push.

## Remote PR Merging (gate-merge.sh pr)

- Before merging a remote PR branch (e.g. `refs/remotes/github/pr-16`): `bash scripts/sh/gate-merge.sh pr <branch>` — checks per-commit GPG signatures, English Conventional-Commits subjects, and merge-tree conflicts BEFORE the merge (exit codes: 0 safe / 1 signature / 2 subject / 4 conflict).
- If it fails: **squash-merge** (`git merge --squash`) to one signed, English, conventional commit — or ask the author to rewrite the branch. NEVER merge unsigned commits and re-sign afterwards — that rewrites history and force-pushes the mirror.
- Local agent branches are signed by construction; remote PRs typically are not.

## Domain Partition

- 7 work domains: K kernel / M memory / S sessions / T tools / C card-cell / B bus-services / A bridge-shell. Each agent owns exactly one domain; announce before touching another.
- Shared files register (one writer at a time): `l3.py`, `params/*.py`, `l3/boot/`, `tests/conftest.py`, `test_layer_imports.py`, `config/praxis.yaml`. Cross-domain API additions commit to main first.
- Merge order: K → M/T/S → C/B → A.
