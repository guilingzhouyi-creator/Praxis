#!/usr/bin/env bash
# pre-receive strict — server-side commit-msg gate for pushes to main.
#
# Rejects pushes that contain commits violating:
#   - English only, no CJK
#   - Conventional Commits type(scope): summary ≤72
#   - Exactly one Co-Authored-By trailer
# Mirrors .githooks/commit-msg logic so --no-verify cannot slip to origin.
#
# Install on server: copy to <repo>.git/hooks/pre-receive and chmod +x
# For GitCode/GitHub, this is emulated by .github/workflows/commit-lint.yml
# (server-side pre-receive is not available on SaaS).

set -euo pipefail

# Read ref updates from stdin: <old> <new> <ref>
while read -r oldrev newrev ref; do
  # Only guard pushes to main (and release branches if needed)
  case "$ref" in
    refs/heads/main|refs/heads/release/*) ;;
    *) continue ;;
  esac

  # New branch (oldrev all zeros) — diff against empty tree
  if echo "$oldrev" | grep -qE "^0+$"; then
    range="$newrev"
  else
    range="$oldrev..$newrev"
  fi

  # Skip if no commits (deletion)
  if echo "$newrev" | grep -qE "^0+$"; then
    continue
  fi

  echo "[pre-receive-strict] checking $ref $range" >&2

  # Use the same single source of truth as the local hook
  if [ -f "scripts/py/commit_scan.py" ]; then
    if ! python scripts/py/commit_scan.py --git-range "$range" --check-content 2>&1 | tee /tmp/pre_receive_scan.log; then
      echo "[pre-receive-strict] ❌ commit policy violation in $ref" >&2
      cat /tmp/pre_receive_scan.log >&2
      echo "[pre-receive-strict] Fix messages per AGENTS.md Commit conventions" >&2
      exit 1
    fi
    # Co-Authored-By is checked via --msg for each commit in the range
    while IFS= read -r sha; do
      msg="$(git log -1 --format=%B "$sha")"
      if ! python scripts/py/commit_scan.py --msg "$msg" 2>&1 | tee /tmp/pre_receive_cab.log; then
        echo "[pre-receive-strict] ❌ Co-Authored-By violation in $sha" >&2
        cat /tmp/pre_receive_cab.log >&2
        exit 1
      fi
    done < <(git rev-list "$range" --no-merges 2>/dev/null)
  else
    echo "[pre-receive-strict] ⚠️  commit_scan.py not found — skip" >&2
  fi
done

echo "[pre-receive-strict] OK — all pushed commits strict"
