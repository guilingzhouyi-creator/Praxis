---
name: pr-check
description: Review a PR, feature branch, or pending commit against the Praxis project checklist (English commits, Co-Authored-By trailer, dual-remote push, branch/worktree workflow). Use when preparing a merge or a push, or when asked to review a PR.
disable-model-invocation: true
---

## PR Context
- Diff: !`git diff HEAD~1`
- Description: !`git log -1 --format=%B`
- Branch: !`git branch --show-current`

Review the pending changes against [checklist.md](checklist.md).

For each item, mark pass or fail with a one-line explanation.
Report the failures first, then the full pass/fail summary.
