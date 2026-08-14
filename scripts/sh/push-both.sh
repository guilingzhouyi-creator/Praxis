#!/usr/bin/env bash
# Dual-remote push — push a branch to BOTH remotes (origin + github).
#
# Rationale (see AGENTS.md "Remote strategy & CI"): origin is GitCode
# (canonical source of truth) and github is the CI carrier. Pushing only to
# GitCode silently skips CI — every push MUST go to both remotes.
#
# Usage:
#   bash scripts/sh/push-both.sh [branch]   # default: current branch
#   bash scripts/sh/push-both.sh main       # explicit branch
#
# Exit codes:
#   0 — both remotes pushed successfully
#   1 — remote missing or push failed on either side
#   2 — not inside a git repository

set -u

BRANCH="${1:-$(git branch --show-current 2>/dev/null)}"
if [ -z "$BRANCH" ]; then
  echo "[push-both] ERROR: cannot determine current branch (detached HEAD?)" >&2
  echo "[push-both] usage: bash scripts/sh/push-both.sh [branch]" >&2
  exit 2
fi

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[push-both] ERROR: not inside a git repository" >&2
  exit 2
}

# Verify both remotes exist before pushing anything.
ORIGIN="$(git remote get-url origin 2>/dev/null)" || {
  echo "[push-both] ERROR: remote 'origin' (GitCode) is not configured" >&2
  exit 1
}
GITHUB="$(git remote get-url github 2>/dev/null)" || {
  echo "[push-both] ERROR: remote 'github' (GitHub CI mirror) is not configured" >&2
  echo "[push-both] hint: git remote add github <url>" >&2
  exit 1
}

echo "[push-both] branch:  $BRANCH"
echo "[push-both] origin:  $ORIGIN"
echo "[push-both] github:  $GITHUB"

if [ "$BRANCH" != "main" ]; then
  echo "[push-both] NOTE: pushing non-main branch '$BRANCH' — CI only guards main."
else
  # Mainline merge gate: pushing main means a local merge is about to land
  # on the canonical tree.  Enforce the net-delta policy (see AGENTS.md
  # "Commit conventions") so main is not inflated by tiny commits — small
  # work must accumulate on a feature worktree branch first.
  # MERGE_GATE_SKIP=1 bypasses the gate — justified ONLY for deploying the
  # gate itself (bootstrap) or explicitly reviewed infrastructure merges,
  # and REQUIRES a reason (MERGE_GATE_REASON) for the audit trail.
  echo "[push-both] ── mainline merge gate (origin/main..main) ─────────────"
  if [ "${MERGE_GATE_SKIP:-0}" != "1" ] && \
     ! MAIN_BASE=origin/main bash scripts/sh/verify-main-merge-gate.sh main; then
    echo "[push-both] ❌ mainline merge gate rejected — push aborted." >&2
    echo "[push-both]    Accumulate the net code delta on your worktree" >&2
    echo "[push-both]    branch (target: >= 1000 net lines) before pushing main." >&2
    exit 1
  fi
  if [ "${MERGE_GATE_SKIP:-0}" = "1" ]; then
    if [ -z "${MERGE_GATE_REASON:-}" ]; then
      echo "[push-both] ❌ MERGE_GATE_SKIP=1 requires MERGE_GATE_REASON=<why>." >&2
      echo "[push-both]    (bootstrap / infrastructure merges must leave an audit trail)" >&2
      exit 1
    fi
    echo "[push-both] ⚠️  merge gate skipped (MERGE_GATE_SKIP=1) — reason: ${MERGE_GATE_REASON}"
  fi
fi

FAIL=0

echo "[push-both] -> git push origin $BRANCH"
if ! git push origin "$BRANCH"; then
  echo "[push-both] ERROR: push to origin (GitCode) failed" >&2
  FAIL=1
fi

echo "[push-both] -> git push github $BRANCH"
if ! git push github "$BRANCH"; then
  echo "[push-both] ERROR: push to github (CI mirror) failed" >&2
  FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
  echo "[push-both] OK — pushed to both remotes."
else
  echo "[push-both] FAILED — at least one remote push errored (see above)." >&2
fi
exit "$FAIL"
