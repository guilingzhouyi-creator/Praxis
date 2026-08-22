#!/usr/bin/env bash
# CompletionJudge — machine decides "done", not the agent.
#
# Ratchet-style completion gate (see docs/architecture/completion-judge.md):
# an agent may declare a task complete ONLY after every check below passes.
# The machine returns COMPLETE, PARTIAL or INCOMPLETE with the evidence gap;
# a PASS never reopens once green (ratchet property: forward only).
#
# Checks (all must pass — full mode):
#   1. Tests        — full suite green (pytest tests/, no -x early exit)
#   2. Coverage     — report fail-under threshold (default 60, from pyproject)
#   3. Net delta    — code delta meets the mainline gate (>= 1000 net, or
#                     deletion-dominated / docs-only exemptions)
#   4. Docs sync    — doc-stats drift gate clean (check_doc_stats.py)
#   5. Lint/type    — ruff check + mypy clean
#   6. Audit        — pip-audit dependency CVE scan clean
#   7. Complexity   — no functions longer than 200 lines
#   8. Import cycle — import_cycle_check.py clean
#   9. Singleton    — scan-singletons.py vs conftest _RESETS in sync
#  10. Changelog    — CHANGELOG [Unreleased] present and fresh
#  11. Doc index    — check_doc_index.py clean
#
# Verdicts:
#   COMPLETE    — all 11 checks executed and passed (authorizes "done")
#   PARTIAL     — all EXECUTED checks passed but >= 1 skipped (fast mode:
#                 informative only, never authorizes "done")
#   INCOMPLETE  — at least one executed check failed (evidence gap printed)
# Mode: "full" (no check skipped) or "fast" (>= 1 check skipped via
# --skip=... or COMPLETION_*=0). The record's `mode` field lets
# judge-stats.sh aggregate full and fast runs separately — never mix them.
#
# Every run appends a machine-readable record to the SHARED judge log
# `<main-tree>/.praxis/judge-runs.jsonl` (gitignored runtime data). The log
# lives in the main worktree (resolved via `git rev-parse --git-common-dir`)
# so runs from ANY linked worktree land in the one file the dashboard
# aggregates: scripts/sh/judge-stats.sh.
#
# Usage:
#   bash scripts/sh/verify-completion.sh [--skip <check,...>]
#   COMPLETION_TESTS=0 bash scripts/sh/verify-completion.sh   # skip a check
# Exit: 0 = COMPLETE or PARTIAL (see verdict); 1 = INCOMPLETE (prints missing
# evidence); 2 = usage error
#
# Each check is a separate function so the ratchet can be extended per-domain
# (swap the verifier, get a different tool).

set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "[judge] not in a git repo" >&2; exit 2; }
cd "$ROOT"

# Shared judge log: `--git-common-dir` resolves to the MAIN tree's .git from
# any linked worktree, so every run (any tree) appends to the single JSONL
# the dashboard aggregates — worktree-local logs would go unmeasured.
COMMON_DIR="$(cd "$(git rev-parse --git-common-dir 2>/dev/null || echo "$ROOT/.git")" && pwd)" || COMMON_DIR="$ROOT/.git"
LOG_FILE="${COMMON_DIR%/}/../.praxis/judge-runs.jsonl"
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
RUN_AUDIT="${COMPLETION_AUDIT:-1}"        # pip-audit dependency CVEs
RUN_COMPLEX="${COMPLETION_COMPLEX:-1}"    # long_functions >200 lines
RUN_CYCLE="${COMPLETION_CYCLE:-1}"        # import-cycle-check
RUN_SINGLETON="${COMPLETION_SINGLETON:-1}"  # scan-singletons drift
RUN_CHANGELOG="${COMPLETION_CHANGELOG:-1}"  # CHANGELOG [Unreleased] fresh
RUN_INDEX="${COMPLETION_INDEX:-1}"          # doc-index consistency

SKIP_ARG=""
for a in "$@"; do
  case "$a" in
    --skip=*) SKIP_ARG="${a#--skip=}" ;;
    *) echo "[judge] unknown arg: $a" >&2; exit 2 ;;
  esac
done
IFS=',' read -r -a SKIP_LIST <<< "$SKIP_ARG"
skip() { local k; for k in "${SKIP_LIST[@]}"; do [ "$k" = "$1" ] && return 0; done; return 1; }
[ -n "$SKIP_ARG" ] && { skip tests && RUN_TESTS=0; skip coverage && RUN_COVERAGE=0; skip delta && RUN_DELTA=0; skip docs && RUN_DOCS=0; skip lint && RUN_LINT=0; skip audit && RUN_AUDIT=0; skip complex && RUN_COMPLEX=0; skip cycle && RUN_CYCLE=0; skip singleton && RUN_SINGLETON=0; skip changelog && RUN_CHANGELOG=0; skip index && RUN_INDEX=0; }

# ── fast-mode detection: any skipped check downgrades COMPLETE -> PARTIAL ──
SKIPPED_ANY=0
for v in "$RUN_TESTS" "$RUN_COVERAGE" "$RUN_DELTA" "$RUN_DOCS" "$RUN_LINT" \
         "$RUN_AUDIT" "$RUN_COMPLEX" "$RUN_CYCLE" "$RUN_SINGLETON" \
         "$RUN_CHANGELOG" "$RUN_INDEX"; do
  [ "$v" = "0" ] && SKIPPED_ANY=1
done
MODE="full"
[ "$SKIPPED_ANY" = "1" ] && MODE="fast"

FAILED=0
GAPS=""
# per-check result flags (0=untested/skipped, 1=pass, 2=fail) — logged
S_TESTS=0; S_COVERAGE=0; S_DELTA=0; S_DOCS=0; S_LINT=0
S_AUDIT=0; S_COMPLEX=0; S_CYCLE=0; S_SINGLETON=0; S_CHANGELOG=0; S_INDEX=0

# per-check numeric metrics (null = skipped/unmeasured) — logged for trends
M_TESTS_PASSED=null; M_TESTS_FAILED=null; M_COVERAGE_PCT=null; M_NET_DELTA=null
M_RUFF_ERRORS=null; M_MEGA_FUNCS=null; M_AUDIT_VULNS=null

fail() { GAPS="${GAPS}  ✗ $1
"; FAILED=1; }
pass() { echo "  ✓ $1"; }

echo "[judge] CompletionJudge — machine verdict on 'done'"
echo "[judge] checks: tests=${RUN_TESTS} coverage=${RUN_COVERAGE} delta=${RUN_DELTA} docs=${RUN_DOCS} lint=${RUN_LINT}"

# ── 1+2. Tests + Coverage (single full-suite run) ──────────────────────
# One pytest invocation with --cov yields BOTH dimensions — running the
# full suite twice (once plain, once with coverage) roughly halves the
# wall time of a full-mode judge run (evidence: full runs take ~10 min).
# When either check is skipped individually (--skip=tests or --skip=coverage)
# the other still runs its own dedicated invocation below.
RUN_TOGETHER=0
if [ "$RUN_TESTS" = "1" ] && [ "$RUN_COVERAGE" = "1" ]; then
  RUN_TOGETHER=1
  echo "[judge] ── 1+2. Full test suite + coverage (single run) ──"
  # Bound the xdist worker count: `-n auto` spawns one worker per CPU core,
  # which on many-core/limited-memory hosts (e.g. 32-core WSL with 15GiB)
  # thrashes memory and hangs the suite. Default 4 workers; operators may
  # override with JUDGE_PYTEST_N (0 = single process, safest).
  JUDGE_N="${JUDGE_PYTEST_N:-4}"
  THRESH=$(grep -oE 'fail_under\s*=\s*[0-9]+' pyproject.toml 2>/dev/null | grep -oE '[0-9]+' | head -1)
  THRESH="${THRESH:-60}"
  if python -m pytest tests/ -q --tb=short -n "$JUDGE_N" --cov=src --cov-report=term --cov-fail-under="$THRESH" --ignore=tests/benchmarks/bench_card.py > /tmp/judge_cov.log 2>&1; then
    S_TESTS=1; pass "tests green ($(grep -oE '[0-9]+ passed' /tmp/judge_cov.log | head -1))"
    S_COVERAGE=1; pass "coverage >= $THRESH%"
  else
    # The combined run failed — tests, coverage, or both. Surface the gap.
    S_TESTS=2; S_COVERAGE=2
    tail -5 /tmp/judge_cov.log >&2
    if grep -qE '^TOTAL' /tmp/judge_cov.log; then
      grep -E 'TOTAL|fail_under' /tmp/judge_cov.log | tail -2 >&2
      fail "coverage below $THRESH% (and/or test failures above)"
    else
      fail "test suite has failures (see /tmp/judge_cov.log)"
    fi
  fi
  M_TESTS_PASSED=$(grep -oE '[0-9]+ passed' /tmp/judge_cov.log | head -1 | grep -oE '[0-9]+' || echo null)
  M_TESTS_FAILED=$(grep -oE '[0-9]+ failed' /tmp/judge_cov.log | head -1 | grep -oE '[0-9]+' || echo null)
  M_COVERAGE_PCT=$(grep -E '^TOTAL' /tmp/judge_cov.log | grep -oE '[0-9]+%' | head -1 | tr -d '%' || echo null)
fi

# ── 1. Tests (standalone — coverage skipped) ────────────────────────────
if [ "$RUN_TESTS" = "1" ] && [ "$RUN_TOGETHER" = "0" ]; then
  echo "[judge] ── 1. Full test suite (standalone) ──"
  JUDGE_N="${JUDGE_PYTEST_N:-4}"
  if python -m pytest tests/ -q --tb=short -n "$JUDGE_N" > /tmp/judge_tests.log 2>&1; then
    S_TESTS=1; pass "tests green ($(grep -oE '[0-9]+ passed' /tmp/judge_tests.log | head -1))"
  else
    S_TESTS=2; tail -5 /tmp/judge_tests.log >&2
    fail "test suite has failures (see /tmp/judge_tests.log)"
  fi
  M_TESTS_PASSED=$(grep -oE '[0-9]+ passed' /tmp/judge_tests.log | head -1 | grep -oE '[0-9]+' || echo null)
  M_TESTS_FAILED=$(grep -oE '[0-9]+ failed' /tmp/judge_tests.log | head -1 | grep -oE '[0-9]+' || echo null)
fi

# ── 2. Coverage (standalone — tests skipped) ────────────────────────────
if [ "$RUN_COVERAGE" = "1" ] && [ "$RUN_TOGETHER" = "0" ]; then
  echo "[judge] ── 2. Coverage (standalone, fail-under) ──"
  THRESH=$(grep -oE 'fail_under\s*=\s*[0-9]+' pyproject.toml 2>/dev/null | grep -oE '[0-9]+' | head -1)
  THRESH="${THRESH:-60}"
  JUDGE_N="${JUDGE_PYTEST_N:-4}"
  if python -m pytest tests/ -q --tb=short -n "$JUDGE_N" --cov=src --cov-report=term --cov-fail-under="$THRESH" --ignore=tests/benchmarks/bench_card.py > /tmp/judge_cov.log 2>&1; then
    S_COVERAGE=1; pass "coverage >= $THRESH%"
  else
    S_COVERAGE=2; grep -E "TOTAL|fail_under" /tmp/judge_cov.log | tail -2 >&2
    fail "coverage below $THRESH%"
  fi
  M_COVERAGE_PCT=$(grep -E '^TOTAL' /tmp/judge_cov.log | grep -oE '[0-9]+%' | head -1 | tr -d '%' || echo null)
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
  M_NET_DELTA=$(grep -oE 'net=-?[0-9]+' /tmp/judge_delta.log | head -1 | sed 's/net=//' || echo null)
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

# ── 5. Lint + type (ruff + mypy) ────────────────────────────────────────
# The 11-dimension contract says "ruff + mypy clean"; mypy MUST actually
# run here, not only in CI (local/CI verdicts must agree). mypy unavailable
# is a hard gap (INCOMPLETE), mirroring how a missing verifier can never
# pass the gate.
if [ "$RUN_LINT" = "1" ]; then
  echo "[judge] ── 5. ruff + mypy ──"
  LINT_OK=1
  if [ -f pyproject.toml ]; then
    ruff check src/ tests/ > /tmp/judge_ruff.log 2>&1 || LINT_OK=0
    ruff format --check src/ tests/ >> /tmp/judge_ruff.log 2>&1 || LINT_OK=0
    if command -v mypy >/dev/null 2>&1; then
      mypy src/ --no-namespace-packages --ignore-missing-imports --allow-untyped-calls --allow-untyped-decorators >> /tmp/judge_ruff.log 2>&1 || LINT_OK=0
    else
      echo "mypy not installed — type check cannot run" >> /tmp/judge_ruff.log
      LINT_OK=0
    fi
    if [ "$LINT_OK" = "1" ]; then
      S_LINT=1; pass "ruff + mypy clean"
    else
      S_LINT=2; tail -5 /tmp/judge_ruff.log >&2; fail "ruff/mypy issues"
    fi
    M_RUFF_ERRORS=$(grep -oE 'Found [0-9]+ errors' /tmp/judge_ruff.log | head -1 | grep -oE '[0-9]+' || echo null)
  fi
fi

# ── 6. Dependency CVEs (pip-audit) ───────────────────────────────────────
# Dependency CVE scanning is a security red line: a missing verifier is an
# evidence gap (INCOMPLETE), never a pass — "tool absent" cannot certify
# "no known vulnerabilities".
if [ "$RUN_AUDIT" = "1" ]; then
  echo "[judge] ── 6. Dependency vulnerabilities (pip-audit) ──"
  if ! command -v pip-audit >/dev/null 2>&1; then
    S_AUDIT=2; fail "pip-audit not installed — dependency CVE check cannot run"
  elif pip-audit --progress-spinner off > /tmp/judge_audit.log 2>&1; then
    S_AUDIT=1; pass "no known vulnerable dependencies"
    M_AUDIT_VULNS=0
  else
    S_AUDIT=2; head -5 /tmp/judge_audit.log >&2
    fail "pip-audit found known vulnerabilities"
    M_AUDIT_VULNS=$(grep -oE '[0-9]+ known' /tmp/judge_audit.log | head -1 | grep -oE '[0-9]+' || echo null)
  fi
fi

# ── 7. Complexity (mega-functions) ───────────────────────────────────────
if [ "$RUN_COMPLEX" = "1" ]; then
  echo "[judge] ── 7. Complexity (long_functions >200 lines) ──"
  if python -c "
import sys; sys.path.insert(0, 'scripts/py')
from collect_stats import long_functions
n = long_functions()
print(n)
sys.exit(1 if n > 12 else 0)
" > /tmp/judge_complex.log 2>&1; then
    S_COMPLEX=1; pass "no complexity overload (<=12 mega-functions)"
  else
    S_COMPLEX=2; cat /tmp/judge_complex.log >&2
    fail "too many mega-functions (>12 of >200 lines) — refactor before declaring done"
  fi
  M_MEGA_FUNCS=$(head -1 /tmp/judge_complex.log | grep -oE '[0-9]+' | head -1 || echo null)
fi

# ── 8. Import cycles ─────────────────────────────────────────────────────
if [ "$RUN_CYCLE" = "1" ]; then
  echo "[judge] ── 8. Import cycle check ──"
  if python scripts/py/import_cycle_check.py > /tmp/judge_cycle.log 2>&1; then
    S_CYCLE=1; pass "no circular imports"
  else
    S_CYCLE=2; head -5 /tmp/judge_cycle.log >&2
    fail "circular imports detected"
  fi
fi

# ── 9. Singleton drift (test isolation) ──────────────────────────────────
if [ "$RUN_SINGLETON" = "1" ]; then
  echo "[judge] ── 9. Singleton scan (conftest _RESETS sync) ──"
  if python scripts/py/scan-singletons.py > /tmp/judge_singleton.log 2>&1; then
    S_SINGLETON=1; pass "singletons registered in _RESETS"
  else
    S_SINGLETON=2; head -5 /tmp/judge_singleton.log >&2
    fail "singleton drift — scan-singletons found unregistered module-level state"
  fi
fi

# ── 10. CHANGELOG freshness ──────────────────────────────────────────────
if [ "$RUN_CHANGELOG" = "1" ]; then
  echo "[judge] ── 10. CHANGELOG [Unreleased] freshness ──"
  if python scripts/py/check_changelog.py > /tmp/judge_changelog.log 2>&1; then
    S_CHANGELOG=1; pass "CHANGELOG [Unreleased] includes latest commits"
  else
    S_CHANGELOG=2; head -5 /tmp/judge_changelog.log >&2
    fail "CHANGELOG stale — run make changelog"
  fi
fi

# ── 11. Doc-index consistency ────────────────────────────────────────────
if [ "$RUN_INDEX" = "1" ]; then
  echo "[judge] ── 11. Doc-index consistency ──"
  if python scripts/py/check_doc_index.py > /tmp/judge_index.log 2>&1; then
    S_INDEX=1; pass "doc-index consistent"
  else
    S_INDEX=2; head -5 /tmp/judge_index.log >&2
    fail "doc-index drift — run make doc-index"
  fi
fi

# ── Verdict + quantitative log ───────────────────────────────────────────
VERDICT="INCOMPLETE"
if [ "$FAILED" = "0" ]; then
  if [ "$SKIPPED_ANY" = "1" ]; then
    VERDICT="PARTIAL"
  else
    VERDICT="COMPLETE"
  fi
fi
DURATION=$(( $(date +%s) - T0 ))

# JSONL record: one line per run, gitignored — the raw material for
# judge-stats.sh (completion rate, failure distribution, trend, metrics).
# Each metric falls back to null when the check did not run or produced no
# parseable value — an empty string would corrupt the JSONL line.
RECORD="{\"ts\":\"${TS}\",\"verdict\":\"${VERDICT}\",\"mode\":\"${MODE}\",\"branch\":\"${BRANCH}\",\"duration_s\":${DURATION},\"checks\":{\"tests\":${S_TESTS},\"coverage\":${S_COVERAGE},\"delta\":${S_DELTA},\"docs\":${S_DOCS},\"lint\":${S_LINT},\"audit\":${S_AUDIT},\"complex\":${S_COMPLEX},\"cycle\":${S_CYCLE},\"singleton\":${S_SINGLETON},\"changelog\":${S_CHANGELOG},\"index\":${S_INDEX}},\"metrics\":{\"tests_passed\":${M_TESTS_PASSED:-null},\"tests_failed\":${M_TESTS_FAILED:-null},\"coverage_pct\":${M_COVERAGE_PCT:-null},\"net_delta\":${M_NET_DELTA:-null},\"ruff_errors\":${M_RUFF_ERRORS:-null},\"mega_funcs\":${M_MEGA_FUNCS:-null},\"audit_vulns\":${M_AUDIT_VULNS:-null}}}"
printf '%s\n' "$RECORD" >> "$LOG_FILE"

echo "[judge] verdict: ${VERDICT}"
if [ "$VERDICT" = "COMPLETE" ]; then
  echo "[judge] ✅ COMPLETE — all 11 checks executed and green (ratchet holds)."
  echo "[judge] logged: $LOG_FILE"
  exit 0
elif [ "$VERDICT" = "PARTIAL" ]; then
  echo "[judge] ⚠️  PARTIAL — fast mode (${MODE}); executed checks green but some skipped; NOT a 'done' verdict." >&2
  echo "[judge] logged: $LOG_FILE" >&2
  exit 0
else
  echo "[judge] ❌ INCOMPLETE — machine says 'not yet'. Evidence gap:" >&2
  printf '%s' "$GAPS" >&2
  echo "[judge]    The agent does not decide 'done'; the machine does." >&2
  echo "[judge] logged: $LOG_FILE" >&2
  exit 1
fi
