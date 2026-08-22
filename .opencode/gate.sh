#!/bin/bash
# Run the sanctioned local-merge gate for a feature branch.
# Usage: gate.sh [tree]   (default: $PRAXIS_TREE, else current repo root)
set -euo pipefail
TREE="${1:-${PRAXIS_TREE:-$(git rev-parse --show-toplevel)}}"
cd "$TREE"
if [ -d ".venv/bin" ]; then export PATH="$PWD/.venv/bin:$PATH"; fi
export PRAXIS_SKIP_AUTHOR_CHECK=1
bash scripts/sh/verify-local-merge.sh
