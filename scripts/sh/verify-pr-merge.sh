#!/usr/bin/env bash
# PR-merge verifier — run BEFORE merging a remote PR branch (e.g. a GitHub PR).
#
# Enforces the pr-check "Incoming commits" gates (see
# .atomcode/skills/pr-check/checklist.md): GitCode's pre-receive hook requires
# EVERY commit on main to be GPG-signed (not just the tip), and the project
# commit conventions require English + Conventional-Commits subjects. Remote
# PRs (GitHub mirror) frequently carry unsigned or placeholder-subject
# commits, so verify BEFORE merging — fixing afterwards rewrites history and
# force-pushes the mirror.
#
# Usage:
#   bash scripts/sh/verify-pr-merge.sh <branch>   # e.g. refs/remotes/github/pr-16
#   bash scripts/sh/verify-pr-merge.sh            # verify the current checkout
#
# Exit codes:
#   0 — safe to merge (all commits signed, subjects conventional, merge clean)
#   1 — signature violation (at least one incoming commit is not GPG-signed)
#   2 — subject violation (non-English or non-Conventional-Commits subject)
#   3 — usage / branch resolution error
#   4 — merge-tree conflict (branch does not merge cleanly onto base)

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[verify-pr-merge] ERROR: not inside a git repository" >&2
  exit 3
}
cd "$ROOT"

MAIN_BASE="${MAIN_BASE:-main}"
BRANCH="${1:-}"
if [ -z "$BRANCH" ]; then
  BRANCH="$(git branch --show-current 2>/dev/null || true)"
fi
if [ -z "$BRANCH" ] || ! git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  echo "[verify-pr-merge] ERROR: cannot resolve branch '$BRANCH'" >&2
  echo "[verify-pr-merge] usage: bash scripts/sh/verify-pr-merge.sh <branch>" >&2
  exit 3
fi
if ! git rev-parse --verify "$MAIN_BASE" >/dev/null 2>&1; then
  echo "[verify-pr-merge] ERROR: cannot resolve base '$MAIN_BASE'" >&2
  echo "[verify-pr-merge] (override with MAIN_BASE=<ref>)" >&2
  exit 3
fi

echo "[verify-pr-merge] branch: $BRANCH (base: $MAIN_BASE)"
MERGE_BASE="$(git merge-base "$MAIN_BASE" "$BRANCH")"
echo "[verify-pr-merge] merge-base: $(git rev-parse --short "$MERGE_BASE")"

RANGE="$MERGE_BASE..$BRANCH"
if [ -z "$(git rev-list "$RANGE" 2>/dev/null || true)" ]; then
  echo "[verify-pr-merge] INFO: no incoming commits — nothing to verify."
  exit 0
fi

# ── 1. Signature check: every incoming commit must be GPG-signed ──────────
# %G? shows: G=good, U=good-but-unknown-validity, T=trust-unknown (accepted);
# N=no signature, B=bad, X/Y/R/E=expired/revoked/unverifiable (rejected).
# PR_MERGE_RELAX_SIGNATURE=1 additionally accepts E (signature cannot be
# checked — e.g. a CI runner that lacks the signing key); N/B always fail.
echo "[verify-pr-merge] ── 1. GPG signature check ───────────────────────────"
if [ "${PR_MERGE_RELAX_SIGNATURE:-0}" = "1" ]; then
  UNSIGNED="$(git log --format='%h %G? %s' "$RANGE" | awk '$2 == "N" || $2 == "B" {print}')"
else
  UNSIGNED="$(git log --format='%h %G? %s' "$RANGE" | awk '$2 !~ /^[GUT]$/ {print}')"
fi
if [ -n "$UNSIGNED" ]; then
  echo "[verify-pr-merge] ❌ UNSIGNED / BAD-SIGNATURE commits:" >&2
  printf '%s\n' "$UNSIGNED" | sed 's/^/     ✗ /' >&2
  echo "[verify-pr-merge]    GitCode pre-receive rejects any unsigned commit on main." >&2
  echo "[verify-pr-merge]    Fix: squash-merge to one signed commit, or ask the author" >&2
  echo "[verify-pr-merge]    to re-sign/rewrite the branch (never re-sign after merge)." >&2
  exit 1
fi
COUNT="$(git rev-list --count "$RANGE")"
echo "[verify-pr-merge] ✅ all $COUNT incoming commits GPG-signed."

# ── 2. Subject check: English + Conventional Commits ──────────────────────
echo "[verify-pr-merge] ── 2. Subject check (English + Conventional Commits) ──"
SUBJECT_RE='^(feat|fix|perf|docs|refactor|style|test|chore|build|ci|revert)(\([a-z0-9_.-]+\))?!?: '
BAD_SUBJECT="$(git log --format='%h|%s' "$RANGE" | while IFS='|' read -r h s; do
  case "$s" in
    Merge\ *|Revert\ *) continue ;;  # git-generated subjects are exempt
  esac
  if printf '%s' "$s" | grep -qP '[\x{4e00}-\x{9fa5}]'; then
    echo "$h|CJK subject: $s"
  elif ! printf '%s' "$s" | grep -qE "$SUBJECT_RE"; then
    echo "$h|non-conventional subject: $s"
  fi
done)"
if [ -n "$BAD_SUBJECT" ]; then
  echo "[verify-pr-merge] ❌ subject violations:" >&2
  printf '%s\n' "$BAD_SUBJECT" | sed 's/^/     ✗ /' >&2
  echo "[verify-pr-merge]    Subjects must be English Conventional Commits" >&2
  echo "[verify-pr-merge]    (\`type(scope): summary\`). Fix the branch or squash-merge." >&2
  exit 2
fi
echo "[verify-pr-merge] ✅ all subjects English + Conventional Commits."

# ── 3. Diff scope: inventory the incoming changes ─────────────────────────
echo "[verify-pr-merge] ── 3. Diff scope ─────────────────────────────────────"
CHANGED="$(git diff --name-only "$MERGE_BASE" "$BRANCH")"
if [ -z "$CHANGED" ]; then
  echo "[verify-pr-merge] INFO: no diff vs base."
  exit 0
fi
N_FILES="$(printf '%s\n' "$CHANGED" | wc -l | tr -d ' ')"
echo "[verify-pr-merge] changed files ($N_FILES):"
printf '%s\n' "$CHANGED" | sed 's/^/     /'

# ── 4. Merge conflict pre-check (merge-tree --write-tree) ─────────────────
echo "[verify-pr-merge] ── 4. Merge conflict pre-check ───────────────────────"
if git merge-tree --write-tree "$MAIN_BASE" "$BRANCH" >/dev/null 2>&1; then
  echo "[verify-pr-merge] ✅ merge is clean (no conflicts vs $MAIN_BASE)."
else
  echo "[verify-pr-merge] ❌ merge-tree reports conflicts vs $MAIN_BASE." >&2
  echo "[verify-pr-merge]    Resolve on the branch before merging." >&2
  exit 4
fi

echo "[verify-pr-merge] OK — safe to merge. Push BOTH remotes afterwards:"
echo "    bash scripts/sh/push-both.sh main"
exit 0
