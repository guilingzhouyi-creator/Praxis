#!/usr/bin/env bash
# Mainline merge gate — reject small/under-threshold code merges into main.
#
# Policy (see AGENTS.md "Commit conventions"): mainline must not be
# inflated by many tiny commits.  A merge into main is allowed only when
# the NET code delta (added − deleted, code paths only) has reached a
# threshold; docs changes are exempt; deletion-dominated merges are
# exempt.  Below the threshold, the change must stay on its feature
# worktree branch and accumulate until the net delta qualifies.
#
# Thresholds (overridable — tighten via env for stricter repos):
#   MERGE_GATE_TINY_MIN     — floor: below this a merge is "tiny" (default 600)
#   MERGE_GATE_QUALIFY_MIN  — qualifying net code delta (default 1000)
#   MERGE_GATE_DOC_MAX      — docs-only ceiling (default 5000)
TINY_MIN="${MERGE_GATE_TINY_MIN:-600}"
QUALIFY_MIN="${MERGE_GATE_QUALIFY_MIN:-1000}"
DOC_MAX="${MERGE_GATE_DOC_MAX:-5000}"

# Usage:
#   bash scripts/sh/verify-main-merge-gate.sh [branch]   # default: current
#   MAIN_BASE=<ref> bash scripts/sh/verify-main-merge-gate.sh [branch]
#
# Exit codes:
#   0 — merge allowed (net delta >= QUALIFY_MIN, deletion-dominated, or docs-only within ceiling)
#   1 — merge rejected (net code delta below threshold / docs-only over ceiling)
#   2 — usage / branch resolution error
#   3 — git/classify tooling failure

# set -u (legacy, kept — this gate intentionally does not use top-level
# set -euo; its commands rely on explicit error handling)

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[merge-gate] ERROR: not inside a git repository" >&2
  exit 3
}
cd "$ROOT"

MAIN_BASE="${MAIN_BASE:-main}"
BRANCH="${1:-}"
if [ -z "$BRANCH" ]; then
  BRANCH="$(git branch --show-current 2>/dev/null || true)"
fi
if [ -z "$BRANCH" ] || ! git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  echo "[merge-gate] ERROR: cannot resolve branch '$BRANCH'" >&2
  echo "[merge-gate] usage: bash scripts/sh/verify-main-merge-gate.sh [branch]" >&2
  exit 2
fi
if ! git rev-parse --verify "$MAIN_BASE" >/dev/null 2>&1; then
  echo "[merge-gate] ERROR: cannot resolve base '$MAIN_BASE'" >&2
  echo "[merge-gate] (override with MAIN_BASE=<ref>)" >&2
  exit 2
fi

if [ "${MERGE_GATE_SKIP:-0}" = "1" ]; then
  if [ -z "${MERGE_GATE_REASON:-}" ]; then
    echo "[merge-gate] ❌ MERGE_GATE_SKIP=1 requires MERGE_GATE_REASON=<why>." >&2
    exit 1
  fi
  echo "[merge-gate] ⚠️  merge gate waived (MERGE_GATE_SKIP=1) — reason: ${MERGE_GATE_REASON}"
  exit 0
fi

if [ "$BRANCH" = "$MAIN_BASE" ]; then
  echo "[merge-gate] INFO: branch '$BRANCH' is the base itself — nothing to gate."
  exit 0
fi

echo "[merge-gate] branch: $BRANCH (base: $MAIN_BASE)"
MERGE_BASE="$(git merge-base "$MAIN_BASE" "$BRANCH")"
RANGE="$MERGE_BASE..$BRANCH"
if [ -z "$(git rev-list "$RANGE" 2>/dev/null || true)" ]; then
  echo "[merge-gate] INFO: no incoming commits — nothing to gate."
  exit 0
fi

# ── 1. Net code delta via classify_diff.py (code paths only) ─────────────
# classify_diff.py reports code_lines = added + deleted for code paths and
# is_large.  For a NET delta we need added − deleted; recompute from
# --numstat so deletion-dominated changes (allowed) are distinguishable.
NUMSTAT_FILE="$(mktemp)"
trap 'rm -f "$NUMSTAT_FILE"' EXIT
if ! git diff --numstat "$MERGE_BASE" "$BRANCH" > "$NUMSTAT_FILE" 2>/dev/null; then
  echo "[merge-gate] ERROR: git diff --numstat failed" >&2
  exit 3
fi

CLASSIFY="scripts/py/classify_diff.py"
if [ ! -f "$CLASSIFY" ]; then
  echo "[merge-gate] ERROR: $CLASSIFY not found" >&2
  exit 3
fi

ADDED=0
DELETED=0
DOC_LINES=0
DOCS_ONLY=1
CODE_PREFIXES="src/ tests/ config/ scripts/ .github/ .githooks/ locales/ .gitcode/"
CODE_FILES="pyproject.toml Makefile Dockerfile docker-compose.yml .pre-commit-config.yaml .gitleaks.toml codecov.yml .editorconfig .gitattributes .mcp.json"
DOC_PREFIXES="docs/"
DOC_FILES="README.md AGENTS.md CHANGELOG.md LICENSE .praxis-rules.md"

while IFS=$'\t' read -r a d path; do
  [ -n "$path" ] || continue
  if [ "$a" = "-" ] || [ "$d" = "-" ]; then
    continue  # binary — not counted
  fi
  a="${a:-0}"
  d="${d:-0}"
  is_code=0
  for p in $CODE_PREFIXES; do
    case "$path" in
      "$p"*) is_code=1 ;;
    esac
  done
  for f in $CODE_FILES; do
    [ "$path" = "$f" ] && is_code=1
  done
  if [ "$is_code" = "0" ]; then
    # docs or unknown — check docs exemption
    is_doc=0
    for p in $DOC_PREFIXES; do
      case "$path" in
        "$p"*) is_doc=1 ;;
      esac
    done
    for f in $DOC_FILES; do
      [ "$path" = "$f" ] && is_doc=1
    done
    if [ "$is_doc" = "0" ]; then
      is_code=1  # unclassified counts as code (never slips through)
    else
      DOC_LINES=$((DOC_LINES + a + d))
      DOCS_ONLY=0  # has doc changes but keep scanning for code files
    fi
  else
    DOCS_ONLY=0
  fi
  if [ "$is_code" = "1" ]; then
    ADDED=$((ADDED + a))
    DELETED=$((DELETED + d))
  fi
done < "$NUMSTAT_FILE"

# ── 1b. Comment-stripped code delta (LOCK 1: no padding with comments) ───
# Count ADDED lines that are pure comments (per-extension comment markers)
# and subtract them from the net delta — the delta reflects REAL code, not
# comment padding.  A comment share >= 60% of added lines is a hygiene
# failure (LOCK 3) — padding with comments cannot pass the gate.
COMMENT_ADDED=0
if [ "$ADDED" -gt 0 ]; then
  COMMENT_ADDED=$(python3 - "$MERGE_BASE" "$BRANCH" <<'PY'
import subprocess, sys
base, head = sys.argv[1], sys.argv[2]
paths = ["src", "tests", "config", "scripts", ".github", ".githooks", "locales", ".gitcode"]
out = subprocess.run(
    ["git", "diff", "-U0", base, head, "--", *paths],
    capture_output=True, text=True,
).stdout
markers = {
    ".py": "#", ".sh": "#", ".yml": "#", ".yaml": "#", ".toml": "#",
    ".md": "#", ".c": ("//", "/*"), ".h": ("//", "/*"),
    ".js": ("//", "/*"), ".ts": ("//", "/*"), ".rs": ("//", "/*"), ".go": ("//", "/*"),
}
cur_ext = ""
comments = 0
for line in out.splitlines():
    if line.startswith("+++ b/"):
        name = line[6:]
        cur_ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    elif line.startswith("+") and not line.startswith("+++"):
        content = line[1:].lstrip()
        m = markers.get(cur_ext)
        if isinstance(m, str):
            if content.startswith(m):
                comments += 1
        elif m and any(content.startswith(x) for x in m):
            comments += 1
print(comments)
PY
)
fi
# Hygiene: comment share of added code lines must stay below 60%.
if [ "$ADDED" -gt 0 ]; then
  COMMENT_SHARE=$(( COMMENT_ADDED * 100 / ADDED ))
else
  COMMENT_SHARE=0
fi

NET=$((ADDED - COMMENT_ADDED - DELETED))
TOTAL=$((ADDED + DELETED))
echo "[merge-gate] code delta: +$ADDED / -$DELETED (net=$NET, comment_lines=$COMMENT_ADDED, share=${COMMENT_SHARE}%)"

# ── 2. Decision ──────────────────────────────────────────────────────────
# Docs-only within ceiling → allowed (docs exemption, but bounded).
if [ "$NET" -eq 0 ] && [ "$TOTAL" -eq 0 ] && [ "$DOC_LINES" -gt 0 ]; then
  if [ "$DOC_LINES" -le "$DOC_MAX" ]; then
    echo "[merge-gate] ✅ docs-only change ($DOC_LINES lines <= $DOC_MAX) — exempt from the net-delta gate."
    echo "[merge-gate] OK — merge allowed."
    exit 0
  fi
  echo "[merge-gate] ❌ REJECTED — docs-only change of $DOC_LINES lines exceeds the $DOC_MAX ceiling." >&2
  echo "[merge-gate]    Docs still need accumulation on a worktree branch." >&2
  exit 1
fi

# LOCK 3: comment-padding hygiene — a change that is mostly comments is
# rejected outright (padding cannot pass as real code).
if [ "$COMMENT_SHARE" -ge 60 ]; then
  echo "[merge-gate] ❌ REJECTED — $COMMENT_SHARE% of added lines are comments (>= 60% hygiene ceiling)." >&2
  echo "[merge-gate]    Real code change required; comment padding cannot pass the gate." >&2
  exit 1
fi

# LOCK 2: deletion is a symmetric gate — deletion-dominated changes are NOT
# an automatic exemption.  Net deletions must also accumulate (mirror the
# net-addition thresholds) so code cannot be churned (add + delete) to game
# the gate.  A net <= 0 change qualifies only when the deleted volume is
# >= QUALIFY_MIN, and is rejected while it is still small.
if [ "$NET" -le 0 ] && [ "$TOTAL" -gt 0 ]; then
  NET_DEL=$((DELETED - ADDED))   # positive when deletion-dominated
  if [ "$NET_DEL" -ge "$QUALIFY_MIN" ]; then
    echo "[merge-gate] ✅ deletion-dominated (net -$NET_DEL lines >= $QUALIFY_MIN) — removal qualifies."
    echo "[merge-gate] OK — merge allowed."
    exit 0
  fi
  echo "[merge-gate] ❌ REJECTED — deletion net -$NET_DEL < $QUALIFY_MIN (symmetric removal gate)." >&2
  echo "[merge-gate]    Deletions must accumulate on the worktree branch like additions;" >&2
  echo "[merge-gate]    churning code (add + delete) to game the gate is not allowed." >&2
  exit 1
fi

if [ "$NET" -ge "$QUALIFY_MIN" ]; then
  echo "[merge-gate] ✅ net code delta $NET >= $QUALIFY_MIN — qualifies for mainline merge."
  echo "[merge-gate] OK — merge allowed."
  exit 0
fi

# Rejected — net code delta below threshold.
if [ "$NET" -lt "$TINY_MIN" ]; then
  REASON="net code delta $NET < $TINY_MIN (tiny change)"
else
  REASON="net code delta $NET < $QUALIFY_MIN (not yet accumulated)"
fi
echo "[merge-gate] ❌ REJECTED — $REASON." >&2
echo "[merge-gate]    To keep mainline from being inflated by repeated small" >&2
echo "[merge-gate]    commits, please accumulate the net delta on your own" >&2
echo "[merge-gate]    worktree branch (target: >= 1000 net code lines) and" >&2
echo "[merge-gate]    only then merge locally into main." >&2
echo "[merge-gate]    Waiver note: the branch pre-merge waiver (MERGE_GATE_SKIP=1" >&2
echo "[merge-gate]    + MERGE_GATE_REASON) is the ONLY path to merge early — it" >&2
echo "[merge-gate]    is granted by the user, never self-awarded. It waives WHEN" >&2
echo "[merge-gate]    a branch merges, NOT where you edit (that is the separate" >&2
echo "[merge-gate]    main-tree modification waiver). Ask the user, do not bypass." >&2

# ── 3. Sibling-branch alignment hint (same merge-base) ───────────────────
SIBLINGS="$(git for-each-ref --format='%(refname:short)' refs/heads \
  | grep -vE "^(main|$BRANCH)$" \
  | while read -r b; do
      [ "$(git merge-base "$MAIN_BASE" "$b" 2>/dev/null)" = "$MERGE_BASE" ] && echo "$b"
    done)"
if [ -n "$SIBLINGS" ]; then
  echo "[merge-gate]    ℹ️ sibling branch(es) on the same merge-base:" >&2
  printf '%s\n' "$SIBLINGS" | sed 's/^/         - /' >&2
  echo "[merge-gate]    Align changes with them before merging when possible;" >&2
  echo "[merge-gate]    conflicts will be reviewed by the merge Agent afterwards." >&2
fi
exit 1
