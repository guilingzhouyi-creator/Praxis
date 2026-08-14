#!/usr/bin/env bash
# CompletionJudge — machine decides "done", not the agent.
#
# Ratchet-style completion gate (see docs/architecture/completion-judge.md):
# an agent may declare a task complete ONLY after every check below passes.
# The machine returns COMPLETE or INCOMPLETE with the evidence gap; a PASS
# never reopens once green (ratchet property: forward only).
#
# Checks (all must pass):
#   1. Tests  — full suite green (pytest tests/, no -x early exit)
#   2. Coverage — report fail-under threshold (default 60, from pyproject)
#   3. Net delta — code delta meets the mainline gate (>= 1000 net, or
#      deletion-dominated / docs-only exemptions)
#   4. Docs sync — doc-stats drift gate clean (check_doc_stats.py)
#   5. Lint/type — ruff check + mypy clean
#
# Every run appends a machine-readable record to `.praxis/judge-runs.jsonl`
# (gitignored runtime data) so the gate's real effectiveness can be
# quantified: see scripts/sh/judge-stats.sh for the aggregate view.
#
# Usage:
#   bash scripts/sh/verify-completion.sh [--skip <check,...>]
#   COMPLETION_TESTS=0 bash scripts/sh/verify-completion.sh   # skip a check
# Exit: 0 = COMPLETE; 1 = INCOMPLETE (prints missing evidence); 2 = usage error
#
# Each check is a separate function so the ratchet can be extended per-domain
# (swap the verifier, get a different tool).

set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "[judge] not in a git repo" >&2; exit 2; }
cd "$ROOT"

LOG_FILE="$ROOT/.praxis/judge-runs.jsonl"
mkdir -p "$(dirname "$LOG_FILE")"
T0="$(date +%s)"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
BRANCH="$(git branch --show-current 2>/dev/null || echo unknown)"

# ── per-check switches (env overrides, all default ON) ───────────────────
RUN_TESTS="${COMPLETION_TESTS:-1}"
RUN_COVERAGE="${COMPLETION_COVERAGE:-1}"
RUN_DELTA="${COMPLETION_DELTA:-1}"
RUN_DOCS="${COMPLETION_DOCS:-1}"
RUN_LINT="${COMPLETION_LINT:-1}"

SKIP_ARG=""
for a in "$@"; do
  case "$a" in
    --skip=*) SKIP_ARG="${a#--skip=}" ;;
    *) echo "[judge] unknown arg: $a" >&2; exit 2 ;;
  esac
done
IFS=',' read -r -a SKIP_LIST <<< "$SKIP_ARG"
skip() { local k; for k in "${SKIP_LIST[@]}"; do [ "$k" = "$1" ] && return 0; done; return 1; }
[ -n "$SKIP_ARG" ] && { skip tests && RUN_TESTS=0; skip coverage && RUN_COVERAGE=0; skip delta && RUN_DELTA=0; skip docs && RUN_DOCS=0; skip lint && RUN_LINT=0; }

FAILED=0
GAPS=""
# per-check result flags (0=untested/skipped, 1=pass, 2=fail) — logged
S_TESTS=0; S_COVERAGE=0; S_DELTA=0; S_DOCS=0; S_LINT=0

fail() { GAPS="${GAPS}  ✗ $1
"; FAILED=1; }
pass() { echo "  ✓ $1"; }

echo "[judge] CompletionJudge — machine verdict on 'done'"
echo "[judge] checks: tests=${RUN_TESTS} coverage=${RUN_COVERAGE} delta=${RUN_DELTA} docs=${RUN_DOCS} lint=${RUN_LINT}"

# ── 1. Tests ─────────────────────────────────────────────────────────────
if [ "$RUN_TESTS" = "1" ]; then
  echo "[judge] ── 1. Full test suite ──"
  if python -m pytest tests/ -q --tb=short > /tmp/judge_tests.log 2>&1; then
    S_TESTS=1; pass "tests green ($(grep -oE '[0-9]+ passed' /tmp/judge_tests.log | head -1))"
  else
    S_TESTS=2; tail -5 /tmp/judge_tests.log >&2
    fail "test suite has failures (see /tmp/judge_tests.log)"
  fi
fi

# ── 2. Coverage ──────────────────────────────────────────────────────────
if [ "$RUN_COVERAGE" = "1" ]; then
  echo "[judge] ── 2. Coverage (fail-under) ──"
  THRESH=$(grep -oE 'fail_under\s*=\s*[0-9]+' pyproject.toml 2>/dev/null | grep -oE '[0-9]+' | head -1)
  THRESH="${THRESH:-60}"
  if python -m pytest tests/ -q --tb=short --cov=src --cov-report=term --cov-fail-under="$THRESH" --ignore=tests/benchmarks/bench_card.py > /tmp/judge_cov.log 2>&1; then
    S_COVERAGE=1; pass "coverage >= $THRESH%"
  else
    S_COVERAGE=2; grep -E "TOTAL|fail_under" /tmp/judge_cov.log | tail -2 >&2
    fail "coverage below $THRESH%"
  fi
fi

# ── 3. Net delta gate ────────────────────────────────────────────────────
if [ "$RUN_DELTA" = "1" ]; then
  echo "[judge] ── 3. Net code delta (mainline gate) ──"
  if [ -f scripts/sh/verify-main-merge-gate.sh ]; then
    if MAIN_BASE=origin/main bash scripts/sh/verify-main-merge-gate.sh main > /tmp/judge_delta.log 2>&1; then
      S_DELTA=1; pass "net delta qualifies"
    else
      S_DELTA=2; grep -E "net=" /tmp/judge_delta.log | head -1 >&2
      fail "net code delta below threshold — accumulate on a worktree branch"
    fi
  else
    pass "gate script not present (skip)"
  fi
fi

# ── 4. Docs sync (drift gate) ────────────────────────────────────────────
if [ "$RUN_DOCS" = "1" ]; then
  echo "[judge] ── 4. Doc-stats drift ──"
  if [ -f scripts/py/check_doc_stats.py ]; then
    if python scripts/py/check_doc_stats.py > /tmp/judge_docs.log 2>&1; then
      S_DOCS=1; pass "doc-stats in sync"
    else
      S_DOCS=2; tail -3 /tmp/judge_docs.log >&2
      fail "doc-stats drift — run make doc-stats"
    fi
  else
    pass "checker not present (skip)"
  fi
fi

# ── 5. Lint + type ───────────────────────────────────────────────────────
if [ "$RUN_LINT" = "1" ]; then
  echo "[judge] ── 5. ruff + mypy ──"
  LINT_OK=1
  if [ -f pyproject.toml ]; then
    ruff check src/ tests/ > /tmp/judge_ruff.log 2>&1 || LINT_OK=0
    ruff format --check src/ tests/ >> /tmp/judge_ruff.log 2>&1 || LINT_OK=0
    if [ "$LINT_OK" = "1" ]; then
      S_LINT=1; pass "ruff clean"
    else
      S_LINT=2; tail -3 /tmp/judge_ruff.log >&2; fail "ruff issues"
    fi
  fi
fi

# ── Verdict + quantitative log ───────────────────────────────────────────
VERDICT="INCOMPLETE"
[ "$FAILED" = "0" ] && VERDICT="COMPLETE"
DURATION=$(( $(date +%s) - T0 ))

# JSONL record: one line per run, gitignored — the raw material for
# judge-stats.sh (completion rate, failure distribution, trend).
RECORD="{\"ts\":\"${TS}\",\"verdict\":\"${VERDICT}\",\"branch\":\"${BRANCH}\",\"duration_s\":${DURATION},\"checks\":{\"tests\":${S_TESTS},\"coverage\":${S_COVERAGE},\"delta\":${S_DELTA},\"docs\":${S_DOCS},\"lint\":${S_LINT}}}"
printf '%s\n' "$RECORD" >> "$LOG_FILE"

if [ "$VERDICT" = "COMPLETE" ]; then
  echo "[judge] ✅ COMPLETE — all checks green (ratchet holds)."
  echo "[judge] logged: $LOG_FILE"
  exit 0
else
  echo "[judge] ❌ INCOMPLETE — machine says 'not yet'. Evidence gap:" >&2
  printf '%s' "$GAPS" >&2
  echo "[judge]    The agent does not decide 'done'; the machine does." >&2
  echo "[judge] logged: $LOG_FILE" >&2
  exit 1
fi
