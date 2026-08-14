#!/usr/bin/env bash
# judge-stats — quantify the CompletionJudge's real effectiveness.
#
# Aggregates `.praxis/judge-runs.jsonl` (written by verify-completion.sh)
# into evidence the gate actually works:
#   - runs / completion rate
#   - INCOMPLETE distribution: which check failed most often
#   - trend: completion rate by day (is slacking being caught more?)
#
# Usage:
#   bash scripts/sh/judge-stats.sh [--days N] [--json]
#   --days N   limit trend window to last N days (default: all)
#   --json     machine-readable summary (for dashboards/CI)
# Exit: 0 always (statistics are informational).

set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "[judge-stats] not in a git repo" >&2; exit 2; }
cd "$ROOT"

LOG="$ROOT/.praxis/judge-runs.jsonl"
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
    *) echo "[judge-stats] unknown arg: $a" >&2; exit 2 ;;
  esac
done

if [ ! -f "$LOG" ]; then
  echo "[judge-stats] no data yet — run verify-completion.sh first ($LOG)" >&2
  exit 0
fi

python3 - "$LOG" "$DAYS" "$JSON" "$MD" "$WRITE" <<'PY'
import json
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

# window filter
if days:
    cutoff = date.today() - timedelta(days=int(days))
    rows = [r for r in rows if datetime.fromisoformat(r["ts"].replace("Z", "+00:00")).date() >= cutoff]

total = len(rows)
complete = sum(1 for r in rows if r["verdict"] == "COMPLETE")
rate = complete / total if total else 0.0

# failure distribution: which check failed (flag == 2) among INCOMPLETE runs
fail_counter = Counter()
incomplete = [r for r in rows if r["verdict"] == "INCOMPLETE"]
for r in incomplete:
    for chk, flag in (r.get("checks") or {}).items():
        if flag == 2:
            fail_counter[chk] += 1

# trend: completion rate per day (ISO date)
trend = defaultdict(lambda: [0, 0])
for r in rows:
    d = datetime.fromisoformat(r["ts"].replace("Z", "+00:00")).date().isoformat()
    trend[d][1] += 1
    if r["verdict"] == "COMPLETE":
        trend[d][0] += 1

if as_json:
    print(json.dumps({
        "total": total,
        "complete": complete,
        "incomplete": total - complete,
        "completion_rate": round(rate, 3),
        "failures_by_check": dict(fail_counter),
        "trend": {d: {"complete": c, "runs": t, "rate": round(c / t, 3)} for d, (c, t) in sorted(trend.items())},
    }))
    sys.exit(0)

if as_md:
    lines = []
    lines.append("## CompletionJudge effectiveness (auto-updated)")
    lines.append("")
    lines.append(f"**Runs**: {total} | **COMPLETE**: {complete} ({rate:.0%}) | **INCOMPLETE**: {total - complete} ({1 - rate:.0%}, premature stops caught)")
    lines.append("")
    lines.append("| Date | Runs | Complete | Rate |")
    lines.append("|---|---|---|---|")
    for d, (c, t) in sorted(trend.items()):
        lines.append(f"| {d} | {t} | {c} | {c / t:.0%} |")
    if fail_counter:
        lines.append("")
        lines.append("**Failures by check** (which gate caught premature stops):")
        for chk, n in fail_counter.most_common():
            lines.append(f"- `{chk}`: {n} ({n / max(len(incomplete), 1):.0%} of incomplete)")
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
print(f"  COMPLETE:        {complete} ({rate:.0%})")
print(f"  INCOMPLETE:      {total - complete} ({1 - rate:.0%})  ← premature stops caught")
print("-" * 52)
if fail_counter:
    print("  failure distribution (INCOMPLETE runs):")
    for chk, n in fail_counter.most_common():
        print(f"    {chk:<10} {n:>4}  ({n / max(len(incomplete), 1):.0%} of incomplete)")
else:
    print("  no check failures recorded.")
print("-" * 52)
print("  trend (completion rate per day):")
for d, (c, t) in sorted(trend.items()):
    print(f"    {d}  {c}/{t}  ({c / t:.0%})")
print("=" * 52)
PY
