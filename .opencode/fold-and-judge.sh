#!/bin/bash
# Fold doc-stats/changelog regen into the merge commit, then judge CLEAN (no env leaks).
set -e
cd /home/guiling/dev/praxis-l2-opt
export PATH="/home/guiling/dev/praxis/.venv/bin:/usr/bin:/bin"
make doc-stats > /tmp/ds.txt 2>&1 || { cat /tmp/ds.txt; exit 1; }
make changelog > /tmp/cl.txt 2>&1 || { cat /tmp/cl.txt; exit 1; }
git add -A
if ! git diff --cached --quiet; then
  git -c core.hooksPath=.githooks commit -q --amend --no-edit
fi
git status --short
echo "=== judge ==="
timeout 900 bash scripts/sh/verify-completion.sh > /tmp/judge11.txt 2>&1 || true
grep -e verdict -e "✗" /tmp/judge11.txt
