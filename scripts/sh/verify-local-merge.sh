#!/usr/bin/env bash
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
# Exit codes:
#   0 — branch qualifies to merge into local main (--no-ff)
#   1 — branch does NOT qualify (net delta below threshold / hygiene)
#   2 — usage / branch resolution error
#   3 — git / tooling failure

set -u

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
echo "[local-merge] running the mainline merge gate with MAIN_BASE=main (local, not origin/main)..."

GATE="scripts/sh/verify-main-merge-gate.sh"
if [ ! -f "$GATE" ]; then
  echo "[local-merge] ERROR: $GATE not found" >&2
  exit 3
fi

MAIN_BASE=main bash "$GATE" "$BRANCH"
RC=$?
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
