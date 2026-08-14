#!/usr/bin/env python3
"""Benchmark trend library — persistent history + regression summary.

Records benchmark results into ``tests/benchmarks/trends.json`` (a rolling
history of the most recent runs) and prints a trend summary comparing the
latest runs against the baseline. Complements ``benchmark.yml``'s single-run
baseline comparison with cross-run trend tracking.

Usage:
  python scripts/py/bench_trends.py record <wall> <steps> [run_id] [ts]
  python scripts/py/bench_trends.py summary            # show rolling trend

Exit code 0 on success; 1 on malformed input or I/O error.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

TRENDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tests", "benchmarks", "trends.json")
BASELINE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "tests", "benchmarks", "baseline.json"
)
TREND_KEEP = 30  # rolling window of recorded runs
SUMMARY_WINDOW = 5  # recent runs averaged for the trend summary
# Regression hard line (percent worse than baseline that fails CI) — the
# single source of truth lives in l1/kernel/params (BENCH_REGRESSION_LIMIT_PCT).
try:
    from l1.kernel.params.system import BENCH_REGRESSION_LIMIT_PCT

    REGRESSION_LIMIT = float(BENCH_REGRESSION_LIMIT_PCT)
except Exception:  # pragma: no cover — standalone script fallback
    REGRESSION_LIMIT = 10.0  # percent worse than baseline that triggers a warning


def _load(path: str, default: list) -> list:
    if not os.path.isfile(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else default
    except (OSError, ValueError):
        return default


def _save(path: str, data: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _baseline() -> dict | None:
    if not os.path.isfile(BASELINE_FILE):
        return None
    try:
        with open(BASELINE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def record(wall: float, steps: float, run_id: str = "", ts: str = "") -> int:
    """Append one run to the trend history, keeping the rolling window."""
    try:
        wall_f = float(wall)
        steps_f = float(steps)
    except (TypeError, ValueError):
        print(f"bench-trends: invalid numbers: wall={wall!r} steps={steps!r}", file=sys.stderr)
        return 1
    trends = _load(TRENDS_FILE, [])
    trends.append({"wall_time": wall_f, "steps_per_sec": steps_f, "run_id": run_id, "ts": ts or "now"})
    trends = trends[-TREND_KEEP:]
    try:
        os.makedirs(os.path.dirname(TRENDS_FILE), exist_ok=True)
        _save(TRENDS_FILE, trends)
    except OSError as e:
        print(f"bench-trends: write failed: {e}", file=sys.stderr)
        return 1
    print(f"recorded: wall={wall_f:.3f}s steps={steps_f:.1f} (history={len(trends)})")
    return 0


def summary() -> int:
    """Print a rolling trend summary vs the baseline."""
    trends = _load(TRENDS_FILE, [])
    base = _baseline()
    if not trends:
        print("bench-trends: no trend history yet")
        return 0
    recent = trends[-SUMMARY_WINDOW:]
    avg_wall = statistics.mean(r["wall_time"] for r in recent)
    avg_steps = statistics.mean(r["steps_per_sec"] for r in recent)
    print(f"trends: {len(trends)} runs recorded, last {len(recent)} averaged")
    print(f"  avg wall_time={avg_wall:.3f}s avg steps/s={avg_steps:.1f}")
    if base:
        base_wall = float(base.get("wall_time", 0))
        if base_wall > 0:
            worse = (avg_wall - base_wall) / base_wall * 100
            flag = " ⚠ REGRESSION" if worse > REGRESSION_LIMIT else ""
            print(f"  vs baseline {base_wall:.3f}s: {worse:+.1f}%{flag}")
            if worse > REGRESSION_LIMIT:
                return 1
    else:
        print("  (no baseline yet — first run)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="record one benchmark run")
    rec.add_argument("wall", help="wall time seconds")
    rec.add_argument("steps", help="steps per second")
    rec.add_argument("run_id", nargs="?", default="")
    rec.add_argument("ts", nargs="?", default="")
    sub.add_parser("summary", help="print rolling trend summary")
    args = parser.parse_args()
    if args.cmd == "record":
        return record(args.wall, args.steps, args.run_id, args.ts)
    return summary()


if __name__ == "__main__":
    sys.exit(main())
