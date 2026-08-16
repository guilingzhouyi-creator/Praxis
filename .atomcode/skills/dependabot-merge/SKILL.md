---
name: dependabot-merge
description: Use when a Dependabot PR/branch needs merging in the Praxis repo — dependency-bump validation, dependency-only diff scope, verify-deps-merge.sh, local GPG-signed merge, and dual-remote push. Do NOT auto-approve dependency PRs.
---

## Overview

Dependabot opens dependency PRs automatically (`.github/dependabot.yml`: weekly pip, monthly GitHub Actions). They are NOT auto-merged — every dependabot branch must go through the double-green merge flow below.

## Merge Gate (Do This, In Order)

1. **Confirm scope**: the branch must touch ONLY the allowed dependency files (repo root only): `pyproject.toml`, `requirements*.txt`, `uv.lock`, `poetry.lock`. Anything else in the branch is a violation.
2. **Run the verify script**: `bash scripts/sh/verify-deps-merge.sh <branch>` — diff-scope check + full-suite run when dependency files changed.
3. **Validate the bump locally**: after touching `pyproject.toml` run `pip install -e ".[test]"` then the FULL suite (`python -m pytest tests/`). A green PR CI is not sufficient — the merge commit itself must pass locally.
4. **Merge locally, never on GitHub**: dependabot bot commits are unsigned and GitHub-side merges break the flow. `git merge <branch>` locally (signing is optional on this repo — the GitCode GPG hook is NOT enabled — but keep the convention), then push.
5. **Push BOTH remotes**: `bash scripts/sh/push-both.sh main` (origin/GitCode FIRST, github=GitHub CI carrier; auto-refreshes doc-stats + judge record + dashboard).
6. **Machine verdict on the merged result**: `bash scripts/sh/verify-completion.sh` should report COMPLETE before the push is considered final.

## Hook Mechanics (Understand the Gate)

- The `commit-msg` hook runs BEFORE the commit object exists, so `HEAD` still points at the previous commit. The merge gate reads the incoming branch from `.git/MERGE_HEAD` during `git merge` (git removes it after commit), falling back to `HEAD^2` only for manual post-merge commits.
- Detection triggers on the merged-tip **author** (`dependabot[bot]`) OR the message — a hand-typed message cannot bypass it. It is NOT triggered by ordinary feature-branch merges.
- Use git's default merge message (`Merge remote-tracking branch 'dependabot/...'`); a hand-typed lowercase message gets full checks.

## Forbidden Paths

- `git merge --no-verify` / `git commit --no-verify` and `PRAXIS_SKIP_AUTHOR_CHECK=1` are deliberate escape hatches for broken-hook recovery ONLY. A `--no-verify` dependabot merge that drags in code WILL slip through the local gate (server-side backstops: GitCode's GPG hook + `deps.yml` PR gate) — if it happened, the merge MUST be reviewed by a second agent before push.
- Dependabot merges on the GitHub UI are outright rejected by GitCode (unsigned commits) — merge locally only.

## CI Backstop

- `.github/workflows/deps.yml` runs on any PR touching dependency files — enforces the dependency-only diff scope + full suite.
- The shared whitelist (hook / verify script / deps.yml, repo root only): `pyproject.toml`, `requirements*.txt`, `uv.lock`, `poetry.lock`.
