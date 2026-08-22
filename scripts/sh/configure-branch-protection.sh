#!/usr/bin/env bash
# Configure GitHub branch protection for main.
#
# Usage:
#   GH_TOKEN=<personal-access-token> bash scripts/sh/configure-branch-protection.sh
#
# Enforces on `main`:
#   - required status checks: Test / CI / Comment audit (+ PR review workflow
#     once it exists) — PRs cannot merge with failing checks
#   - required approving review: 1
#   - enforce_admins: true (even admins must pass the gates)
#
# Requires a GitHub PAT with `repo` scope (admin:org not needed for repo
# protection). The token is read from the environment ONLY — never store or
# echo it.

set -euo pipefail

REPO="${REPO:-guilingzhouyi-creator/Praxis}"
BRANCH="main"

if [ -z "${GH_TOKEN:-}" ]; then
  echo "[branch-protection] ERROR: GH_TOKEN is required (read from env, never committed)." >&2
  echo "[branch-protection] usage: GH_TOKEN=<pat> bash scripts/sh/configure-branch-protection.sh" >&2
  exit 1
fi

API="https://api.github.com/repos/$REPO/branches/$BRANCH/protection"

# Required checks by actual GitHub check-run context (workflow job names,
# NOT workflow names — branch protection matches the job context exactly).
# "review" = pr-review.yml job; "static"/"comment-audit"/"lint" =
# test.yml / comment-audit.yml / ci.yml jobs; "test (3.x)" = test matrix.
CHECKS=(
  "test (3.11)"
  "test (3.12)"
  "test (3.13)"
  "test (3.14)"
  "static"
  "comment-audit"
  "lint"
  "review"
)

BODY=$(python3 - "$(IFS=,; echo "${CHECKS[*]}")" <<'PY'
import json, sys
checks = [c for c in sys.argv[1].split(",") if c]
print(json.dumps({
    "required_status_checks": {
        "strict": True,
        "contexts": checks,
    },
    "enforce_admins": True,
    "required_pull_request_reviews": {
        "required_approving_review_count": 1,
    },
    "restrictions": None,
}))
PY
)

echo "[branch-protection] configuring $REPO:$BRANCH ..."
RESP=$(curl -sS -X PUT "$API" \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -d "$BODY")

if echo "$RESP" | grep -q '"enabled": true\|"required_approving_review_count"'; then
  echo "[branch-protection] ✅ protection applied:"
  echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print('  checks:', d.get('required_status_checks',{}).get('contexts')); print('  reviews:', d.get('required_pull_request_reviews',{}).get('required_approving_review_count')); print('  enforce_admins:', d.get('enforce_admins'))"
else
  echo "[branch-protection] ❌ failed:" >&2
  echo "$RESP" | head -c 500 >&2
  echo >&2
  exit 1
fi
