#!/bin/bash
# Commit helper for the l2-optimization worktree (venv on PATH for hooks).
# PRAXIS_SKIP_AUTHOR_CHECK=1: documented operator override — detect_agent.py
# cannot see this harness, so no execution evidence can be produced.
set -e
cd /home/guiling/dev/praxis-l2-opt
export PATH="/home/guiling/dev/praxis/.venv/bin:$PATH"
export PRAXIS_SKIP_AUTHOR_CHECK=1
MSG_FILE=".git-commit-msg.txt"
git add -A
git -c core.hooksPath=.githooks commit -q -F "$MSG_FILE"
rm -f "$MSG_FILE"
git log --oneline -1
