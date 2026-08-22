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
  echo "[push-both] ── doc-stats refresh (numbers must not go stale) ───────"
  if make doc-stats >/dev/null 2>&1; then
    # If the refresh changed generated docs, commit them so the merged
    # main never carries stale line/file counts (README/llms).
    if [ -n "$(git status --porcelain docs/ README.md 2>/dev/null)" ]; then
      git add docs/ README.md 2>/dev/null
      git commit --no-verify -m "docs(stats): refresh snapshot before mainline merge" \
        -m "Auto-refresh by push-both: doc-stats numbers must not go stale." \
        -m "Co-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>" >/dev/null 2>&1 \
        && echo "[push-both] ✅ doc-stats snapshot committed" \
        || echo "[push-both] ⚠️  doc-stats drift present but could not auto-commit — refresh manually" >&2
    else
      echo "[push-both] ✅ doc-stats in sync (no changes)"
    fi
  else
    echo "[push-both] ⚠️  make doc-stats failed — numbers may be stale" >&2
  fi

  echo "[push-both] ── completion judge (statistics record) ────────────────"
  # Record a judge run for every mainline push attempt (JSONL audit trail
  # consumed by judge-stats.sh). Fast mode: skip the slow test/coverage
  # sweeps — the merge gate itself already ran the delta check; tests were
  # gated by the worktree before merge. The verdict is PARTIAL in fast mode
  # (never COMPLETE) — the record's `mode` field keeps the dashboard honest.
  if bash scripts/sh/verify-completion.sh --skip=tests,coverage >/tmp/pushboth_judge.log 2>&1; then
    JV="$(grep -oE 'verdict: [A-Z]+' /tmp/pushboth_judge.log | head -1 | awk '{print $2}')"
    echo "[push-both] ✅ completion judge: ${JV:-PARTIAL} (fast mode — tests/coverage skipped; full-gate verdict comes from the worktree run)"
  else
    echo "[push-both] ⚠️  completion judge: INCOMPLETE (see /tmp/pushboth_judge.log)" >&2
  fi

  echo "[push-both] ── judge dashboard (aggregate → docs/judge-stats.md) ───"
  # Regenerate the committed dashboard so the CI/nightly job always reads a
  # fresh aggregate (JSONL itself stays gitignored in .praxis/). The
  # aggregation is O(n) over the log — milliseconds even with hundreds of
  # runs — and writes a small Markdown file (never the raw log).
  if bash scripts/sh/judge-stats.sh --md --write=docs/judge-stats.md >/tmp/pushboth_dash.log 2>&1; then
    if [ -n "$(git status --porcelain docs/judge-stats.md 2>/dev/null)" ]; then
      git add docs/judge-stats.md 2>/dev/null
      git commit --no-verify -m "docs(stats): refresh judge dashboard" \
        -m "Auto-refresh by push-both: CompletionJudge aggregate must stay current." \
        -m "Co-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>" >/dev/null 2>&1 \
        && echo "[push-both] ✅ judge dashboard refreshed" \
        || echo "[push-both] ⚠️  dashboard drift present but could not auto-commit" >&2
    else
      echo "[push-both] ✅ judge dashboard in sync"
    fi
  else
    echo "[push-both] ⚠️  judge dashboard refresh failed (see /tmp/pushboth_dash.log)" >&2
  fi

  echo "[push-both] ── mainline merge gate (origin/main..main) ─────────────"
  if [ "${MERGE_GATE_SKIP:-0}" != "1" ] && \
     ! MAIN_BASE=origin/main bash scripts/sh/verify-main-merge-gate.sh main; then
    echo "[push-both] ❌ mainline merge gate rejected — push aborted." >&2
    echo "[push-both]    Accumulate the net code delta on your worktree" >&2
    echo "[push-both]    branch (target: >= 1000 net lines) before pushing main." >&2
    echo "[push-both]    Waiver note: early merge needs the BRANCH PRE-MERGE" >&2
    echo "[push-both]    WAIVER (MERGE_GATE_SKIP=1 + MERGE_GATE_REASON), granted" >&2
    echo "[push-both]    by the user only — it waives WHEN a branch merges, NOT" >&2
    echo "[push-both]    where you edit (that is the separate main-tree" >&2
    echo "[push-both]    modification waiver). Ask the user; never self-waive." >&2
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

# ── Commit audit (main branch only) — catch --no-verify bypasses ─────────
if [ "$BRANCH" = "main" ]; then
  echo "[push-both] ── commit audit (origin/main..main) ──────────────────────"
  AHEAD=$(git rev-list --count "origin/main..main" 2>/dev/null || echo 0)
  if [ "$AHEAD" -gt 0 ] && [ -f scripts/py/commit_scan.py ]; then
    if ! python scripts/py/commit_scan.py --git-range origin/main..main --check-content >/tmp/pushboth_commit_scan.log 2>&1; then
      echo "[push-both] ❌ commit audit FAILED — push aborted." >&2
      cat /tmp/pushboth_commit_scan.log >&2
      echo "[push-both]    Fix violations before pushing, or use --no-verify locally" >&2
      echo "[push-both]    (but remember: the mainline gate protects the canonical tree)." >&2
      exit 1
    fi
    echo "[push-both] ✅ commit audit passed (${AHEAD} commit(s) checked)"
  fi
fi

# ── Shared-file registration check (soft — warn, don't block) ────────────
# Un-pushed commits touching shared files should register in the handoff
# area so parallel agents can reconcile (see docs/agent-handoff/).
if [ "$BRANCH" = "main" ]; then
  SHARED_CHANGED="$(git diff --name-only origin/main..HEAD 2>/dev/null | grep -E '^(scripts/sh/|\.githooks/|config/discovery/)' | head -1 || true)"
  ALIGN_TOUCHED="$(git diff --name-only origin/main..HEAD 2>/dev/null | grep -c '^docs/agent-handoff/ALIGNMENT.md' || true)"
  if [ -n "$SHARED_CHANGED" ] && [ "$ALIGN_TOUCHED" = "0" ]; then
    echo "[push-both] ⚠️  Shared file(s) changed ($SHARED_CHANGED) without ALIGNMENT.md registration — consider registering in docs/agent-handoff/ (soft warning)." >&2
  fi
fi

# ── Handoff-area growth check (soft — archive at threshold) ──────────────
HANDOFF_ENTRIES="$(grep -c '^| 202[0-9]-' docs/agent-handoff/ALIGNMENT.md 2>/dev/null || true)"
if [ "${HANDOFF_ENTRIES:-0}" -gt "${HANDOFF_LOG_MAX:-30}" ]; then
  echo "[push-both] ⚠️  Handoff area grew ($HANDOFF_ENTRIES log entries > ${HANDOFF_LOG_MAX:-30}) — run bash scripts/sh/handoff-rotate.sh to archive old entries." >&2
fi

# ── Push-safety pre-check (dual-push reliability) ────────────────────────
# Before pushing, surface how many local commits are NOT yet on origin —
# a silent skip here is the #1 cause of the "local != origin" drift that
# parallel worktrees produce. Also warn when origin has moved past local
# (concurrent push): the push below would be rejected non-fast-forward.
echo "[push-both] ── push-safety pre-check ────────────────────────────────"
AHEAD_ORIGIN=$(git rev-list --count "origin/$BRANCH..$BRANCH" 2>/dev/null || echo 0)
BEHIND_ORIGIN=$(git rev-list --count "$BRANCH..origin/$BRANCH" 2>/dev/null || echo 0)
echo "[push-both] local ahead of origin: $AHEAD_ORIGIN commit(s); behind: $BEHIND_ORIGIN"
if [ "$BEHIND_ORIGIN" -gt 0 ]; then
  echo "[push-both] ⚠️  local is BEHIND origin by $BEHIND_ORIGIN (concurrent push?) — push may be rejected." >&2
  echo "[push-both]    Run: git fetch origin && git rebase origin/$BRANCH (or merge) first." >&2
fi

echo "[push-both] -> git push origin $BRANCH"
if ! git push origin "$BRANCH"; then
  echo "[push-both] ERROR: push to origin (GitCode) failed" >&2
  echo "[push-both]    if rejected as non-fast-forward: git fetch origin && git rebase origin/$BRANCH" >&2
  FAIL=1
fi

echo "[push-both] -> git push github $BRANCH"
if ! git push github "$BRANCH"; then
  echo "[push-both] ERROR: push to github (CI mirror) failed" >&2
  echo "[push-both]    if rejected as non-fast-forward: git fetch github && git rebase github/$BRANCH" >&2
  FAIL=1
fi

# ── Post-push verification: the two remotes must agree ───────────────────
if [ "$FAIL" -eq 0 ]; then
  echo "[push-both] ── post-push verification ────────────────────────────────"
  LOCAL_SHA=$(git rev-parse "$BRANCH")
  ORIGIN_SHA=$(git ls-remote origin "$BRANCH" 2>/dev/null | cut -f1)
  GITHUB_SHA=$(git ls-remote github "$BRANCH" 2>/dev/null | cut -f1)
  echo "[push-both] local=$LOCAL_SHA origin=$ORIGIN_SHA github=$GITHUB_SHA"
  if [ "$LOCAL_SHA" = "$ORIGIN_SHA" ] && [ "$LOCAL_SHA" = "$GITHUB_SHA" ]; then
    echo "[push-both] ✅ three-way consistent."
  else
    echo "[push-both] ⚠️  three-way MISMATCH — re-run push-both or fetch to confirm." >&2
    FAIL=1
  fi
fi

if [ "$FAIL" -eq 0 ]; then
  echo "[push-both] OK — pushed to both remotes."
else
  echo "[push-both] FAILED — at least one remote push errored (see above)." >&2
fi
exit "$FAIL"
