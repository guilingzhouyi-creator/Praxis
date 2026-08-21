#!/bin/bash
# Run the sanctioned local-merge gate for the feature branch.
set -e
cd /home/guiling/dev/praxis-l2-opt
export PATH="/home/guiling/dev/praxis/.venv/bin:/usr/bin:/bin"
export PRAXIS_SKIP_AUTHOR_CHECK=1
bash scripts/sh/verify-local-merge.sh
