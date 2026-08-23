#!/usr/bin/env bash
set -euo pipefail
# Local-merge gate — decide whether the CURRENT feature branch may merge
# into LOCAL main.
#
# The push gate (verify-main-merge-gate.sh, run by push-both.sh) only checks
# origin/main..main at PUSH time — it answers "may main be pushed to the
# remotes?".  This gate answers the EARLIER question: "has THIS branch
# accumulated enough (net code delta) to merge into local main?".  Run it
# BEFORE `git merge --no-ff main` — semi-finished work never enters mainline,
# and a branch must reach the quantitative threshold before its proposal is
# merged, not just before it is pushed.
#
# It delegates the quantitative decision to verify-main-merge-gate.sh with
# MAIN_BASE=main (the local mainline, not origin/main), so the three locks
# (comment stripping / symmetric deletion / hygiene ceiling) and the
# docs-only exemption apply identically.
#
# Usage:
#   bash scripts/sh/verify-local-merge.sh [branch]   # default: current branch
#
# Anti "forgot the tests" notice: if the most recent judge run skipped the
# tests dimension, warn before the merge proceeds (soft — evidence, not block).
# Exit codes:
#   0 — branch qualifies to merge into local main (--no-ff)
#   1 — branch does NOT qualify (net delta below threshold / hygiene)
#   2 — usage / branch resolution error
#   3 — git / tooling failure

# set -u covered by top-level set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[local-merge] ERROR: not inside a git repository" >&2
  exit 3
}
cd "$ROOT"

BRANCH="${1:-}"
if [ -z "$BRANCH" ]; then
  BRANCH="$(git branch --show-current 2>/dev/null || true)"
fi
if [ -z "$BRANCH" ]; then
  echo "[local-merge] ERROR: cannot determine current branch (detached HEAD?)" >&2
  echo "[local-merge] usage: bash scripts/sh/verify-local-merge.sh [branch]" >&2
  exit 2
fi
if ! git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  echo "[local-merge] ERROR: cannot resolve branch '$BRANCH'" >&2
  exit 2
fi

# A branch cannot "merge into itself" — this gate is for feature branches.
if [ "$BRANCH" = "main" ]; then
  echo "[local-merge] INFO: '$BRANCH' is main itself — local-merge gate applies to feature branches only." >&2
  echo "[local-merge] (the push gate already covers main; nothing to gate locally)" >&2
  exit 0
fi

echo "[local-merge] branch: $BRANCH (target: local main)"

# ── Sensitive-path hunk audit ───────────────────────────────────────────
# Roadmaps and discovery registries are stateful; a stale branch snapshot
# must not replace either tree as one opaque hunk. Keep this before the
# quantitative gate so an otherwise-qualifying branch cannot bypass review.
HUNK_AUDIT="scripts/py/audit_merge_hunks.py"
if [ ! -f "$HUNK_AUDIT" ]; then
  echo "[local-merge] ERROR: $HUNK_AUDIT not found" >&2
  exit 3
fi
echo "[local-merge] ── sensitive-path hunk audit (main..$BRANCH) ──"
if python "$HUNK_AUDIT" --base main --head "$BRANCH" --check; then
  HUNK_RC=0
else
  HUNK_RC=$?
fi
if [ "$HUNK_RC" -ne 0 ]; then
  if [ "$HUNK_RC" -eq 2 ]; then
    echo "[local-merge] ❌ hunk audit tooling failed." >&2
    exit 3
  fi
  echo "[local-merge] ❌ sensitive-path hunk audit rejected the branch." >&2
  echo "[local-merge]    Review docs/roadmaps/ and config/discovery/ hunks before merging." >&2
  exit 1
fi
echo "[local-merge] ✅ sensitive-path hunk audit passed"

# ── Commit audit — every commit on the branch must pass commit_scan ──────
SCAN="scripts/py/commit_scan.py"
if [ -f "$SCAN" ]; then
  echo "[local-merge] ── commit audit (main..$BRANCH) ──"
  if ! python "$SCAN" --git-range "main..$BRANCH" --check-content >/tmp/local_merge_scan.log 2>&1; then
    echo "[local-merge] ❌ commit audit FAILED — branch has violations." >&2
    cat /tmp/local_merge_scan.log >&2
    echo "[local-merge]    Fix the commits before merging, or use MERGE_GATE_SKIP=1 waiver." >&2
    exit 1
  fi
  echo "[local-merge] ✅ commit audit passed"
fi

echo "[local-merge] running the mainline merge gate with MAIN_BASE=main (local, not origin/main)..."

GATE="scripts/sh/verify-main-merge-gate.sh"
if [ ! -f "$GATE" ]; then
  echo "[local-merge] ERROR: $GATE not found" >&2
  exit 3
fi

if MAIN_BASE=main bash "$GATE" "$BRANCH"; then
  RC=0
else
  RC=$?
fi

# ── Anti "forgot the tests" — judge test-state notice (soft) ────────────
# If the most recent judge run skipped the tests dimension, surface it
# before the merge verdict (evidence, not a block).
JUDGE_LOG="$(git rev-parse --git-common-dir 2>/dev/null)/../.praxis/judge-runs.jsonl"
if [ -f "$JUDGE_LOG" ]; then
  LAST_SKIP_TESTS="$(tail -1 "$JUDGE_LOG" 2>/dev/null | grep -o '"skipped_tests":[01]' | grep -o '[01]$' || echo 0)"
  if [ "${LAST_SKIP_TESTS:-0}" = "1" ]; then
    echo "[local-merge] ⚠️  Most recent judge run SKIPPED tests — this branch's tests are not evidenced; run bash scripts/sh/verify-completion.sh (WSL slice-serial) before merging code." >&2
  fi
fi

if [ "$RC" -eq 0 ]; then
  echo ""
  echo "[local-merge] ✅ branch '$BRANCH' qualifies to merge into local main."
  echo "[local-merge]    Next: git merge --no-ff $BRANCH (from main), then double-green"
  echo "[local-merge]    verification + push-both.sh main for the push-time gate."
else
  echo ""
  echo "[local-merge] ❌ branch '$BRANCH' does NOT yet qualify for local main."
  echo ""
  echo "   HOW TO FIX (accumulate, do not force):"
  echo "     1. stay on this worktree branch — keep committing real code"
  echo "        (net delta target >= 1000; docs-only changes do not count)"
  echo "     2. re-check: bash scripts/sh/verify-local-merge.sh"
  echo "     3. once ✅: git switch main && git merge --no-ff $BRANCH"
  echo "     4. then double-green + push: bash scripts/sh/push-both.sh main"
  echo "   Waiver (user-granted ONLY, never self-award): MERGE_GATE_SKIP=1"
  echo "   + MERGE_GATE_REASON=<why> — ask the user, do not bypass."
fi
exit "$RC"
