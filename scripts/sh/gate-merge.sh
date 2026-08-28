#!/usr/bin/env bash
# gate-merge.sh — unified entry point for the merge/completion gate family.
#
# Single file, single responsibility split: every stage below is one
# concrete gate script with its own flags, output and exit contract; this
# dispatcher only routes argv and never inspects it. Legacy file names are
# accepted as aliases so existing runbooks keep working while the docs
# converge on the stage names.
#
# Usage:
#   bash scripts/sh/gate-merge.sh <stage> [args...]
#
# Stages (legacy alias → underlying gate):
#   completion                       ← verify-completion.sh        CompletionJudge "done" ratchet
#   local    (local-merge)           ← verify-local-merge.sh       feature→local-main admission
#   mainline (main-merge-gate)       ← verify-main-merge-gate.sh   net-delta policy gate
#   pr       (pr-merge)              ← verify-pr-merge.sh          remote PR / pre-receive mirror
#   deps     (deps-merge)            ← verify-deps-merge.sh        dependabot dependency-only diff
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/sh/gate-merge.sh <stage> [args...]

Stages:
  completion      run the CompletionJudge ratchet (verify-completion.sh)
  local           feature branch → local main admission gate
  mainline        mainline net-delta / anti-inflation gate
  pr              pre-merge verification mirroring the server pre-receive
  deps            dependabot dependency-merge gate

Aliases kept for legacy runbooks: local-merge, main-merge-gate,
pr-merge, deps-merge. Run "<stage>" with no args for its own usage.
EOF
}

if [ $# -lt 1 ]; then
  usage >&2
  exit 2
fi

STAGE="$1"
shift

# Sweep regenerable build products at every gate entry (shared with
# pre-commit and push-both; see scripts/sh/build-artifact-sweep.sh).
bash scripts/sh/build-artifact-sweep.sh

case "$STAGE" in
  completion)                   exec bash scripts/sh/verify-completion.sh "$@" ;;
  local | local-merge)          exec bash scripts/sh/verify-local-merge.sh "$@" ;;
  mainline | main-merge-gate)   exec bash scripts/sh/verify-main-merge-gate.sh "$@" ;;
  pr | pr-merge)                exec bash scripts/sh/verify-pr-merge.sh "$@" ;;
  deps | deps-merge)            exec bash scripts/sh/verify-deps-merge.sh "$@" ;;
  -h | --help | help)           usage ;;
  *)
    echo "[gate-merge] unknown stage: $STAGE" >&2
    usage >&2
    exit 2
    ;;
esac
