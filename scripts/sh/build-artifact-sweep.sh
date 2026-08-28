#!/usr/bin/env bash
# Build-artifact sweep — remove regenerable report output at gate entry.
#
# Called by .githooks/pre-commit, scripts/sh/gate-merge.sh and
# scripts/sh/push-both.sh so every governance entry point clears gitignored
# build products (vitest coverage/, Python htmlcov/) that accumulate in the
# working tree. Deleting them is safe: the producing commands recreate them.
#
# Cache directories (.pytest_cache/.ruff_cache/.mypy_cache) are intentionally
# NOT swept here — they carry performance value and belong to `make clean`.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$ROOT" ]; then
  # Fallback for linked worktrees where git cannot resolve (e.g. WSL side).
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi
cd "$ROOT"

BUILD_ARTIFACT_DIRS=(
  "systems/typescript-shell-engine/coverage"
  "htmlcov"
)

SWEPT=0
for _dir in "${BUILD_ARTIFACT_DIRS[@]}"; do
  if [ -d "$_dir" ]; then
    rm -rf "$_dir"
    echo "[build-artifact-sweep] removed $_dir (regenerable report)"
    SWEPT=$((SWEPT + 1))
  fi
done
if [ "$SWEPT" -gt 0 ]; then
  echo "[build-artifact-sweep] Reminder to agent: these gitignored build products are"
  echo "[build-artifact-sweep] recreated by their producing commands (e.g. vitest --coverage)."
fi
exit 0
