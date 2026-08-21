#!/bin/bash
# Post-merge double-green: full suite + CompletionJudge on the merged branch.
set -e
cd /home/guiling/dev/praxis-l2-opt
export PATH="/home/guiling/dev/praxis/.venv/bin:/usr/bin:/bin"
export PRAXIS_SKIP_AUTHOR_CHECK=1
timeout 900 bash scripts/sh/verify-completion.sh > /tmp/judge10.txt 2>&1 || true
grep -e verdict -e "✗" -e "tests green" /tmp/judge10.txt
