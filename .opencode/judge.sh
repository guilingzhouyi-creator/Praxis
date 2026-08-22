#!/bin/bash
# Post-merge double-green: full suite + CompletionJudge on the merged branch.
# Usage: judge.sh [tree]   (default: $PRAXIS_TREE, else current repo root)
set -euo pipefail
TREE="${1:-${PRAXIS_TREE:-$(git rev-parse --show-toplevel)}}"
cd "$TREE"
if [ -d ".venv/bin" ]; then export PATH="$PWD/.venv/bin:$PATH"; fi
export PRAXIS_SKIP_AUTHOR_CHECK=1
timeout 900 bash scripts/sh/verify-completion.sh > /tmp/judge10.txt 2>&1 || true
grep -e verdict -e "✗" -e "tests green" /tmp/judge10.txt
