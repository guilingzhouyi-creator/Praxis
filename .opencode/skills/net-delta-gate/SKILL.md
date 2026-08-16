---
name: net-delta-gate
description: Use when merging to main, when a merge is rejected, or when deciding whether work can land — apply the mainline net-delta gate (verify-main-merge-gate.sh, three locks) and the mandatory post-rejection behavior (verify-main-merge-gate.sh, three locks) and follow the mandatory post-rejection behavior. Use before merging to main, when a merge is rejected, or when deciding whether work can land.
---

## The gate

`verify-main-merge-gate.sh` computes the NET code delta (added − deleted,
code paths only; docs exempt) of `origin/main..main`. Run it before any
main merge:

```bash
MAIN_BASE=origin/main bash scripts/sh/verify-main-merge-gate.sh main
```

## Three locks

- **LOCK 1 — comment stripping**: added comment lines are subtracted from
  the delta; only REAL code counts. Padding with comments cannot pass.
- **LOCK 2 — symmetric deletion gate**: deletion-dominated changes are NOT
  an automatic exemption — net deletions must accumulate to ≥ 1000 like
  additions. Churning code (add + delete) to game the gate is rejected.
- **LOCK 3 — hygiene ceiling**: ≥ 60% of added lines as comments is
  rejected outright.

Thresholds: net < 600 → reject; 600–999 → reject; ≥ 1000 → allow;
deletion net ≥ 1000 → allow; docs-only ≤ 5000 → allow.

## Mandatory post-rejection behavior

If the gate rejects the merge, the agent MUST:

1. **Re-examine** — ask "is it REALLY done?"; re-check the CompletionJudge
   verdict and Definition of done.
2. **Never self-waive** — do NOT bypass with `MERGE_GATE_SKIP=1` (or any
   bypass) on your own judgment; a waiver is the human's decision. If you
   believe the rejection is wrong, present the case and ask the user.
3. **Keep accumulating on YOUR worktree branch** — continue committing on
   the same feature worktree branch until the net delta qualifies; do not
   start a new branch from main to dodge the rule.
4. **Ask the user when growth stalls** — if the delta cannot grow further,
   STOP and ask ("should this land despite being below the threshold?").
5. **Every subsequent commit passes the same gate** — a rejection is not a
   free pass for the next attempt.
