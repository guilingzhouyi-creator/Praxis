#!/usr/bin/env bash
set -euo pipefail
# judge-stats — quantify the CompletionJudge's real effectiveness.
#
# Aggregates `.praxis/judge-runs.jsonl` (written by verify-completion.sh)
# into evidence the gate actually works.
#
# INCLUSION CRITERION (what belongs in the committed dashboard):
# The Markdown dashboard (docs/judge-stats.md) is the QUANTITATIVE-STANDARD
# gate surface — it carries only:
#   - gate verdicts (runs / COMPLETE / PARTIAL / INCOMPLETE, full vs fast)
#   - per-check failure distribution (which standard dimension intercepts)
#   - per-check pass rate over executed runs (ratchet evidence)
#   - numeric metric series (coverage / net delta / tests / lint / audit …)
#     — the quantified standards themselves
#   - daily trend of the completion rate (ratchet direction over time)
# Diagnostics that attribute, time or correlate (per-branch completion,
# duration, streaks, failure pairs) are NOT standards — they stay in the
# --json/--text local output for operators and never enter the committed doc.
#
# Statistics conventions: full and fast runs are NEVER mixed in one rate or
# duration figure; records are deduplicated (ts+verdict+branch+duration) and
# ordered by timestamp; gate-exemption count is per commit, not per line.
#
# Usage:
#   bash scripts/sh/judge-stats.sh [--days N] [--json] [--md] [--write=F] [--log=F]
#   --days N   limit trend window to last N days (default: all)
#   --json     machine-readable summary (for dashboards/CI)
#   --md       Markdown report (for docs/judge-stats.md)
#   --write=F  write the --md report to file F
#   --log=F    read runs from file F instead of .praxis/judge-runs.jsonl
#              (for tests / alternate logs)
# Exit: 0 always (statistics are informational).

# set -u covered by top-level set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "[judge-stats] not in a git repo" >&2; exit 2; }
cd "$ROOT"

COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null || true)"
if [ -n "$COMMON_DIR" ] && [ -d "$COMMON_DIR" ]; then
  LOG="$(cd "$COMMON_DIR" && pwd)/../.praxis/judge-runs.jsonl"
else
  LOG="$ROOT/.praxis/judge-runs.jsonl"
fi
DAYS=""
JSON=0
MD=0
WRITE=""
for a in "$@"; do
  case "$a" in
    --days=*) DAYS="${a#--days=}" ;;
    --json) JSON=1 ;;
    --md) MD=1 ;;
    --write=*) WRITE="${a#--write=}" ;;
    --log=*) LOG="${a#--log=}" ;;
    *) echo "[judge-stats] unknown arg: $a" >&2; exit 2 ;;
  esac
done

if [ ! -f "$LOG" ]; then
  echo "[judge-stats] no data yet — run verify-completion.sh first ($LOG)" >&2
  exit 0
fi

python3 - "$LOG" "$DAYS" "$JSON" "$MD" "$WRITE" <<'PY'
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

log, days, as_json, as_md, write_to = sys.argv[1], sys.argv[2], sys.argv[3] == "1", sys.argv[4] == "1", sys.argv[5]
rows = []
with open(log, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue

if not rows:
    print("[judge-stats] log is empty — no runs recorded yet.")
    sys.exit(0)

# Dedupe (concurrent runs / migrated legacy records may repeat) and order
# records by timestamp so "latest" metrics follow wall-clock order.
seen = set()
uniq = []
for r in rows:
    key = (r.get("ts", ""), r.get("verdict", ""), r.get("branch", ""), r.get("duration_s", 0))
    if key in seen:
        continue
    seen.add(key)
    uniq.append(r)
rows = sorted(uniq, key=lambda r: r.get("ts", ""))

# Drop no-op runs: a record whose checks are ALL zero (e.g. a fully-skipped
# fast invocation) executed nothing and must not count toward runs or the
# completion rate. Records without a checks dict (legacy) are kept.
rows = [r for r in rows if not ((r.get("checks") or {}) and all(v == 0 for v in r["checks"].values()))]

# Drop telemetry snapshots (class=telemetry, e.g. push-both's automatic
# post-push probe): they are activity markers, never verdicts — structurally
# PARTIAL in fast mode — and must not dilute completion rates. Counted
# separately so the dashboard still shows pipeline activity.
telemetry_count = sum(1 for r in rows if r.get("class") == "telemetry")
rows = [r for r in rows if r.get("class") != "telemetry"]

# Mode: explicit `mode` field wins; legacy records derive it from the check
# flags (any flag 0 = skipped = fast; <11 checks = legacy fast). Never mix full
# and fast runs in one completion/duration statistic — they measure different things.
def run_mode(r):
    m = r.get("mode")
    if m in ("full", "fast"):
        return m
    chks = r.get("checks") or {}
    if len(chks) < 11 or any(fl == 0 for fl in chks.values()):
        return "fast"
    return "full"

# window filter (UTC-aligned)
if days:
    from datetime import timezone
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=int(days))
    rows = [r for r in rows if datetime.fromisoformat(r["ts"].replace("Z", "+00:00")).date() >= cutoff]

total = len(rows)
full_runs = [r for r in rows if run_mode(r) == "full"]
fast_runs = [r for r in rows if run_mode(r) == "fast"]

# COMPLETE strictly means "all 11 checks executed and passed" (full mode).
# Legacy fast-mode records written as COMPLETE (checks skipped) are
# downgraded to the PARTIAL bucket — the audit-corrected reading.
complete = sum(1 for r in full_runs if r.get("verdict") == "COMPLETE")
partial = sum(1 for r in rows if r.get("verdict") == "PARTIAL" or (r.get("verdict") == "COMPLETE" and run_mode(r) == "fast"))
rate = complete / total if total else 0.0
full_rate = complete / len(full_runs) if full_runs else 0.0
incomplete = [r for r in rows if r.get("verdict") == "INCOMPLETE"]

# failure distribution: which check failed (flag == 2) among INCOMPLETE runs
fail_counter = Counter()
for r in incomplete:
    for chk, flag in (r.get("checks") or {}).items():
        if flag == 2:
            fail_counter[chk] += 1

# trend: per-day verdict stats. Two rates are reported side by side:
#   full_rate  = full-mode COMPLETE / full runs   ("done" gold standard)
#   rate       = legacy mixed denominator kept for continuity
trend = defaultdict(lambda: {"runs": 0, "full_runs": 0, "complete_full": 0})
for r in rows:
    d = datetime.fromisoformat(r["ts"].replace("Z", "+00:00")).date().isoformat()
    trend[d]["runs"] += 1
    if run_mode(r) == "full":
        trend[d]["full_runs"] += 1
        if r.get("verdict") == "COMPLETE":
            trend[d]["complete_full"] += 1

# ── A: per-branch completion rate ──────────────────────────────────────
branch_stats = defaultdict(lambda: {"runs": 0, "complete": 0})
for r in rows:
    b = r.get("branch") or "unknown"
    branch_stats[b]["runs"] += 1
    if r["verdict"] == "COMPLETE" and run_mode(r) == "full":
        branch_stats[b]["complete"] += 1

# ── A: duration avg / P95 (gate efficiency) — split by mode ─────────────
def dur_stats(vals):
    if not vals:
        return {"avg": None, "p95": None, "n": 0}
    return {
        "avg": round(sum(vals) / len(vals), 1),
        "p95": vals[min(int(len(vals) * 0.95), len(vals) - 1)],
        "n": len(vals),
    }

dur_full = dur_stats(sorted(r.get("duration_s", 0) for r in rows if run_mode(r) == "full"))
dur_fast = dur_stats(sorted(r.get("duration_s", 0) for r in rows if run_mode(r) == "fast"))
full_runs = [r for r in rows if run_mode(r) == "full"]
fast_runs = [r for r in rows if run_mode(r) == "fast"]

# ── A: longest consecutive INCOMPLETE streak (chronological) ───────────
streak = 0
max_streak = 0
for r in sorted(rows, key=lambda x: x.get("ts", "")):
    if r["verdict"] == "INCOMPLETE":
        streak += 1
        max_streak = max(max_streak, streak)
    else:
        streak = 0

# ── A: per-check pass rate over executed runs (flag 1 or 2) ────────────
check_pass = defaultdict(lambda: [0, 0])  # chk -> [passes, executed]
for r in rows:
    for chk, flag in (r.get("checks") or {}).items():
        if flag in (1, 2):
            check_pass[chk][1] += 1
            if flag == 1:
                check_pass[chk][0] += 1

# ── A: failure-pair analysis (checks failing together) ─────────────────
pair_counter = Counter()
for r in incomplete:
    failed = sorted(chk for chk, flag in (r.get("checks") or {}).items() if flag == 2)
    for i in range(len(failed)):
        for j in range(i + 1, len(failed)):
            pair_counter[(failed[i], failed[j])] += 1

# ── C: numeric metrics (if present in newer records) ───────────────────
metric_series = defaultdict(list)  # metric -> [values] (non-null only)
for r in rows:
    m = r.get("metrics") or {}
    for k, v in m.items():
        if v is not None and v != "null":
            try:
                metric_series[k].append(float(v))
            except (TypeError, ValueError):
                pass
metrics_summary = {}
for k, vals in metric_series.items():
    if vals:
        metrics_summary[k] = {
            "latest": round(vals[-1], 2),
            "avg": round(sum(vals) / len(vals), 2),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
        }

# Tests-skip count — judge runs that skipped the tests dimension
# (anti "forgot the tests": the dashboard surfaces skipped tests).
skipped_tests_count = sum(1 for r in rows if r.get("skipped_tests") == 1)

# Delta-waiver count — judge runs whose net-delta check passed via the
# MERGE_GATE_SKIP waiver (not because the branch qualified). A waived pass
# is honest evidence of a user-granted exemption, never of a qualifying
# delta; surfacing it keeps completion statistics from absorbing waivers.
delta_waived_count = sum(1 for r in rows if r.get("delta_waived") == 1)

# ── C: gate-exemption count from git history ──────────────────────────
# MERGE_GATE_SKIP=1 waivers leave an audit trail in merge messages
# (push-both requires MERGE_GATE_REASON). Count them per COMMIT (one record
# per commit via null-separated fields) — a message spanning subject+body must
# not be double-counted.
exemptions = 0
try:
    out = subprocess.run(
        ["git", "log", "--all", "-z", "--format=%H%x00%B", "--grep=MERGE_GATE_SKIP"],
        capture_output=True, text=True, timeout=15,
    ).stdout
    entries = [e for e in out.split("\x00") if e.strip()]
    exemption_hashes = set()
    for i in range(0, len(entries) - 1, 2):
        chash = entries[i].strip()
        cmsg = entries[i + 1]
        if "MERGE_GATE_SKIP" in cmsg or "gate exemption" in cmsg.lower():
            exemption_hashes.add(chash)
    exemptions = len(exemption_hashes)
except Exception:
    exemptions = 0

if as_json:
    print(json.dumps({
        "total": total,
        "complete": complete,
        "partial": partial,
        "incomplete": total - complete - partial,
        "completion_rate": round(rate, 3),
        "full_completion_rate": round(full_rate, 3),
        "duration_s": dur_full,
        "duration_fast": dur_fast,
        "mode_runs": {"full": len(full_runs), "fast": len(fast_runs)},
        "max_incomplete_streak": max_streak,
        "gate_exemptions": exemptions,
        "delta_waived_runs": delta_waived_count,
        "failures_by_check": dict(fail_counter),
        "branch_stats": {b: {"runs": s["runs"], "complete": s["complete"], "rate": round(s["complete"] / s["runs"], 3)} for b, s in branch_stats.items()},
        "check_pass_rates": {chk: {"pass": p, "executed": n, "rate": round(p / n, 3)} for chk, (p, n) in check_pass.items()},
        "failure_pairs": ["+".join(pair) for pair, _ in pair_counter.most_common()],
        "metrics": metrics_summary,
        "telemetry_excluded": telemetry_count,
        "trend": {d: {"runs": v["runs"], "full_runs": v["full_runs"], "complete_full": v["complete_full"],
                      "full_rate": round(v["complete_full"] / v["full_runs"], 3) if v["full_runs"] else None,
                      "rate": round(v["complete_full"] / v["runs"], 3) if v["runs"] else None}
                  for d, v in sorted(trend.items())},
    }))
    sys.exit(0)

def pct(part, whole):
    return f"{part / whole:.0%}" if whole else "-"

if as_md:
    lines = []
    lines.append("## CompletionJudge effectiveness (auto-updated)")
    lines.append("")
    lines.append(f"**Runs**: {total} | **COMPLETE**: {complete} ({pct(complete, total)}) | **PARTIAL**: {partial} ({pct(partial, total)}, fast mode — checks skipped) | **INCOMPLETE**: {total - complete - partial} ({pct(total - complete - partial, total)}, machine 'not done')")
    lines.append(f"**Mode split**: full {len(full_runs)} ({pct(complete, len(full_runs))} complete) / fast {len(fast_runs)} (fast = at least one check skipped)")
    lines.append(f"**Full-mode verdict rate**: {complete}/{len(full_runs)} ({pct(complete, len(full_runs))}) — the 'done' gold standard; mixed rates below include fast snapshots")
    if telemetry_count:
        lines.append(f"**Telemetry snapshots excluded from rates**: {telemetry_count} (push-both activity probes)")
    if skipped_tests_count:
        lines.append(f"**Skipped tests notice**: tests skipped in {skipped_tests_count} judge run(s) (full mode / WSL slice-serial required before merge)")
    if exemptions:
        lines.append(f"**Gate exemptions** (MERGE_GATE_SKIP commits in history): {exemptions}")
    if delta_waived_count:
        lines.append(f"**Waived delta passes**: {delta_waived_count} judge run(s) passed net-delta via MERGE_GATE_SKIP (not a qualifying delta)")
    lines.append("")
    lines.append("| Date | Runs | Full Runs | Full Complete | Full Rate | Legacy Rate |")
    lines.append("|---|---|---|---|---|---|")
    for d, v in sorted(trend.items()):
        lines.append(f"| {d} | {v['runs']} | {v['full_runs']} | {v['complete_full']} | {pct(v['complete_full'], v['full_runs'])} | {pct(v['complete_full'], v['runs'])} |")
    if fail_counter:
        lines.append("")
        lines.append("**Failures by check** (most frequent evidence gaps):")
        for chk, n in fail_counter.most_common():
            lines.append(f"- `{chk}`: {n} ({pct(n, len(incomplete))} of incomplete)")
    if check_pass:
        lines.append("")
        lines.append("**Check pass rate** (over executed runs — ratchet evidence):")
        for chk, (p, n) in sorted(check_pass.items()):
            lines.append(f"- `{chk}`: {p}/{n} ({pct(p, n)})")
    if metrics_summary:
        lines.append("")
        lines.append("**Numeric metrics** (latest / avg / min / max):")
        for k, v in sorted(metrics_summary.items()):
            lines.append(f"- `{k}`: {v['latest']} / {v['avg']} / {v['min']} / {v['max']}")
    output = "\n".join(lines) + "\n"
    if write_to:
        import os
        os.makedirs(os.path.dirname(write_to) or ".", exist_ok=True)
        with open(write_to, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"[judge-stats] wrote {write_to}")
    else:
        print(output)
    sys.exit(0)

print("=" * 52)
print("CompletionJudge effectiveness (machine-measured)")
print("=" * 52)
print(f"  runs:            {total}")
print(f"  COMPLETE:        {complete} ({pct(complete, total)})")
print(f"  PARTIAL:         {partial} ({pct(partial, total)})  ← fast mode, checks skipped")
print(f"  INCOMPLETE:      {total - complete - partial} ({pct(total - complete - partial, total)})")
print(f"  mode split:      full {len(full_runs)} / fast {len(fast_runs)}")
if dur_full["n"]:
    print(f"  duration (full): avg {dur_full['avg']:.0f}s / P95 {dur_full['p95']}s ({dur_full['n']} runs)")
if dur_fast["n"]:
    print(f"  duration (fast): avg {dur_fast['avg']:.0f}s / P95 {dur_fast['p95']}s ({dur_fast['n']} runs)")
print(f"  longest streak:  {max_streak} consecutive INCOMPLETE")
print(f"  gate exemptions: {exemptions} (MERGE_GATE_SKIP commits in history)")
print("-" * 52)
if fail_counter:
    print("  failure distribution (INCOMPLETE runs):")
    for chk, n in fail_counter.most_common():
        print(f"    {chk:<10} {n:>4}  ({pct(n, len(incomplete))} of incomplete)")
else:
    print("  no check failures recorded.")
print("-" * 52)
print("  completion rate by branch:")
for b, s in sorted(branch_stats.items(), key=lambda kv: kv[1]["runs"], reverse=True):
    print(f"    {b:<30} {s['complete']}/{s['runs']}  ({pct(s['complete'], s['runs'])})")
print("-" * 52)
print("  check pass rate (executed runs):")
for chk, (p, n) in sorted(check_pass.items()):
    print(f"    {chk:<12} {p:>4}/{n:<4}  ({pct(p, n)})")
if pair_counter:
    print("-" * 52)
    print("  failure pairs (top 5):")
    for pair, n in pair_counter.most_common(5):
        print(f"    {' + '.join(pair):<24} {n:>3}")
print("-" * 52)
print("  trend (full-mode verdict rate per day | legacy mixed rate):")
for d, v in sorted(trend.items()):
    print(f"    {d}  full {v['complete_full']}/{v['full_runs']} ({pct(v['complete_full'], v['full_runs'])})  |  all {v['complete_full']}/{v['runs']} ({pct(v['complete_full'], v['runs'])})")
if telemetry_count:
    print(f"  telemetry snapshots excluded from rates: {telemetry_count}")
if metrics_summary:
    print("-" * 52)
    print("  numeric metrics (latest/avg/min/max):")
    for k, v in sorted(metrics_summary.items()):
        print(f"    {k:<14} {v['latest']:>8} {v['avg']:>8} {v['min']:>8} {v['max']:>8}")
if skipped_tests_count:
    print(f"  ⚠️  tests skipped in {skipped_tests_count} judge run(s) — run verify-completion.sh (WSL slice-serial) before merging code")
print("=" * 52)
PY
