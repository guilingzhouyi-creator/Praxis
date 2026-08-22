# Development Workflow — Lightweight Branching

> Status: active | Applies to all collaborators (humans and agent tools)

Praxis is a multi-writer repository (user + OpenCode / AtomCode / Copilot).
The project reached the branching critical point when an in-flight refactor
(tool_spec) left the working tree half-modified and broke the full test
suite — the mainline lost "always shippable" status. This document defines
the lightweight branching policy that keeps mainline green while multiple
writers and large refactors coexist.

## 1. Core principle

**Semi-finished work never enters mainline.**

Working-tree changes must be either committed or moved to a feature branch.
Half-finished code left in the working tree poisons test verification for
every collaborator.

## 2. Branch model (lightweight, governance-flavored)

```
main          stable, shippable, tests green          ("已生效法律")
feature/*     proposal branch for big changes/refactors ("立法提案")
small changes commit directly to main                  (bug fixes, docs, tests)
```

### Mapping to Praxis governance

| Git concept | Praxis governance |
|-------------|-------------------|
| feature branch | Card in `proposed` state |
| double-green verification | CONFERENCE deliberation (convergence) |
| merge to main | card `approved` (legislation passed) |
| discard branch | proposal rejected (zero pollution) |
| git revert | legislation repeal |

## 3. When to branch

Open a `feature/<name>` branch when ANY of:

- multi-Phase feature work (e.g. the R5 memory-graph build-out)
- refactors touching shared modules (kernel, tool registry, config, memory)
- any change that cannot be verified green in one session
- parallel work by multiple agent tools on overlapping areas
- risky changes (gatechain, L1 kernel, persistence)

Commit directly to main only for:

- single-file bug fixes
- documentation / config tweaks
- test additions that do not change behavior

## 4. Double-green merge rule

A feature branch may merge to main only when:

1. `python -m pytest tests/ -q` passes **on the branch**, and
2. the same suite passes **on main** (baseline check), and
3. commits carry English messages + `Co-Authored-By` (commit-msg hook).

**Local-merge gate (before merging into local main):** run
`bash scripts/sh/verify-local-merge.sh` — it delegates to the mainline
merge gate with `MAIN_BASE=main` and rejects the branch until its net code
delta reaches the threshold (≥ 1000). The push-time gate (push-both.sh)
only guards pushing main to the remotes; the local-merge gate guards the
EARLIER step — the feature branch entering local main at all.

The local gate also runs
`python scripts/py/audit_merge_hunks.py --base main --head <branch> --check`.
Changes under `docs/roadmaps/` and `config/discovery/` are printed at unified
hunk granularity; a one-hunk replacement of an existing file is rejected for
manual review. Use `--json` when attaching the inventory to a merge record.

Merge with `--no-ff` to preserve the proposal record.

## 5. Working-tree hygiene (iron rule)

- Never leave in-flight refactors in the working tree.
- If a change cannot be finished and committed now: `git stash` it **and
  note it** (stash entries get lost when shells are killed), or open a
  branch and commit WIP.
- Check `git stash list` after any interrupted command (killed shells
  skip `git stash pop` — see the R5 Phase-3 incident).

## 6. Mainline protection

- `main` must always pass: `python -m pytest tests/ -q` (or the documented
  batch splits) before push.
- After large branch merges, verify `git log origin/main..HEAD` before push.
- Release points: tag `main` (e.g. `v0.4.x`).

## 6.1 Release flow

- A version tag (`v*`) pushed to `main` triggers the `Release` workflow on
  GitHub (CI carrier): wheel + sdist are built with `python -m build` and
  attached to a GitHub Release with auto-generated notes; the five
  Dockerfile targets are pushed to GHCR with semver tags
  (`v0.4.2-kernel`, `0.4-api`, ...). Prerelease tags (`vX.Y.Z-rc.N`,
  `vX.Y.Z-beta.N`) are marked as prereleases.
- `main` pushes additionally publish GHCR images tagged
  `main-<target>` / `<sha>-<target>` via the `Docker` workflow.
- Local artifact builds: `make release-build` (requires the `build`
  package; output lands in `dist/`). `release/` stays the reserved
  packaging-output placeholder — CI artifacts are not committed.

## 7. Enforcement

- `.githooks/commit-msg` — English messages + Co-Authored-By (already active)
- `.githooks/pre-commit` — ruff + format + size check (already active)
- Branch hygiene is convention-based; the double-green rule is enforced by
  the verifier in the loop (agent collaborators read this document via
  AGENTS.md).

## 8. Branch accumulation quality gate (分支积累质量门禁)

**Trigger — branch accumulation hits a threshold.** When a `feature/*` branch
has accumulated **≥ 5 unmerged commits** AND a **cumulative net code delta
≥ 4000 lines** vs `main`, further commits on that branch are BLOCKED until
the gate clears. The branch must stop advancing and enter the quality-gate
flow below. (`fix*` branches are fully exempt — they carry targeted
defect repairs and may always keep committing.)

**Gate flow (mandatory, in order):**
1. **Review merged code quality.** Run `code_review` over the RECENT code
   that has landed on `main` (the branch's earlier merges — reviewed scope
   is the merged range since the last quality gate). The review is a
   machine verdict, not advisory: it decides whether the merged quality
   still holds.
2. **Targeted fixes.** Every P1/P2 finding from the review MUST be fixed on
   this branch before it can advance again. Fixes land as normal commits on
   the same worktree branch (per `docs/workflow/code-of-conduct.md`).
3. **Clear the branch — merge to main.** Once the review is clean (no
   unresolved P1/P2) and the branch's own work is double-green, the branch
   MUST be merged into `main` (`--no-ff`). The branch is then considered
   CLEARED; only after it is cleared may the agent open the next accumulation
   cycle (new branch / continue in the worktree).

**Why:** accumulation without review lets low-quality merged code pile up
invisibly; the gate couples branch growth to a machine-reviewed quality
floor so a long-lived branch never outruns its own review debt.
