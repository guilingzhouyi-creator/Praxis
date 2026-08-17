"""Per-layer performance baseline scanner — measures runtime throughput per layer.

Complements ``layer_quality.py`` (structural quality) with a runtime
dimension: every layer's benchmark primitives are measured against a stored
baseline in ``config/quality/perf-baseline.yaml``.

Layer mapping (benchmark -> layer):
  - L1: kernel micro benches from ``bench_platform.py --json``
        (mutex.acquire_release / event_bus.emit / channel.put_get /
         worker_pool.submit / thread.create_join)
  - L3: R4 candidate-ledger ingestion from ``bench_r4_candidate_store.py``
        (submit / durable ops/sec), plus security/toolchain cross-link
        microbenchmarks from ``bench_security_toolchain.py``
  - L5: end-to-end card throughput from ``bench_card.py`` (steps/sec)

Gate semantics (mirrors layer_quality.py):
  - hard: a benchmark that errors or is unavailable fails the run.
  - soft (drift): ``ops_per_sec`` must stay above ``PERF_DRIFT_FLOOR``
    (90%) of its baseline — the same 10% regression line used by
    ``.github/workflows/benchmark.yml``.

Exit code 0 = pass, 1 = any gate violated, 2 = baseline missing.

Usage:
    python scripts/py/perf_quality.py                # scan + gate verdict
    python scripts/py/perf_quality.py --report       # measured table only
    python scripts/py/perf_quality.py --baseline     # emit baseline YAML to stdout
    python scripts/py/perf_quality.py --run-json <f> # dump measured JSON (debug)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
BASELINE = ROOT / "config" / "quality" / "perf-baseline.yaml"

PERF_DRIFT_FLOOR = 0.9  # ops_per_sec must stay >= 90% of baseline

# Benchmark -> layer mapping; each entry names the driver script and the
# keys it reports (the drivers' own output formats are parsed below).
_BENCH_PLATFORM = ROOT / "tests" / "benchmarks" / "bench_platform.py"
_BENCH_R4 = ROOT / "tests" / "benchmarks" / "bench_r4_candidate_store.py"
_BENCH_CARD = ROOT / "tests" / "benchmarks" / "bench_card.py"
_BENCH_TOOLCHAIN = ROOT / "tests" / "benchmarks" / "bench_security_toolchain.py"


def _run_driver(args: list[str], timeout: int = 180) -> str:
    """Run a benchmark driver and return its combined stdout/stderr."""
    proc = subprocess.run([sys.executable, *args], capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    return proc.stdout + proc.stderr


def measure_l1() -> dict[str, float]:
    """Run bench_platform --json and extract per-primitive ops/sec (L1)."""
    tmp = ROOT / ".praxis" / "perf_platform.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    _run_driver([str(_BENCH_PLATFORM), "--json", str(tmp), "--rounds", "3"])
    data = json.loads(tmp.read_text(encoding="utf-8"))
    return {name: float(v["ops_per_sec"]) for name, v in data.get("micro", {}).items() if "ops_per_sec" in v}


def measure_l3() -> dict[str, float]:
    """Run bench_r4_candidate_store and extract ingestion ops/sec (L3)."""
    out = _run_driver([str(_BENCH_R4)])
    result: dict[str, float] = {}
    for line in out.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            try:
                result[key.strip()] = float(value.strip())
            except ValueError:
                continue
    return {k: v for k, v in result.items() if k in ("submit_ops_per_sec", "durable_ops_per_sec")}


def measure_toolchain() -> dict[str, float]:
    """Run security/toolchain microbenchmarks and extract ops/sec metrics."""
    out = _run_driver([str(_BENCH_TOOLCHAIN), "--iterations", "100", "--rounds", "3"])
    result: dict[str, float] = {}
    for line in out.splitlines():
        if ":" not in line or not line.split(":", 1)[0].strip().endswith("ops_per_sec"):
            continue
        key, _, value = line.partition(":")
        try:
            result[key.strip()] = float(value.strip())
        except ValueError:
            continue
    return result


def measure_l5() -> dict[str, float]:
    """Run bench_card and extract steps-per-second (L5)."""
    out = _run_driver([str(_BENCH_CARD)])
    for line in out.splitlines():
        if "Steps/s:" in line:
            try:
                return {"card.steps_per_sec": float(line.split(":")[-1].strip())}
            except ValueError:
                return {}
    return {}


def measure_all() -> dict[str, dict[str, float]]:
    """Run every layer benchmark and return {layer: {metric: ops_per_sec}}."""
    l3 = measure_l3()
    l3.update(measure_toolchain())
    return {"L1": measure_l1(), "L3": l3, "L5": measure_l5()}


def load_baseline(path: Path) -> dict[str, Any]:
    """Load the stored per-layer performance baseline YAML (empty when absent)."""
    if not path.exists():
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"perf_quality: baseline load failed: {e}", file=sys.stderr)
        return {}


def compare(measured: dict[str, dict[str, float]], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare measured throughput against the baseline; return finding dicts."""
    findings: list[dict[str, Any]] = []
    layers_baseline = baseline.get("layers", {})
    for layer, metrics in sorted(measured.items()):
        bl = layers_baseline.get(layer, {})
        for name, ops in sorted(metrics.items()):
            base = bl.get(name)
            if base is None:
                findings.append(_finding(layer, name, ops, None, "hard", "no baseline entry"))
                continue
            if ops <= 0.0:
                findings.append(_finding(layer, name, ops, base, "hard", "benchmark error/unavailable"))
                continue
            if ops < base * PERF_DRIFT_FLOOR:
                findings.append(
                    _finding(layer, name, ops, base, "soft", f"below {int(PERF_DRIFT_FLOOR * 100)}% of baseline")
                )
    return findings


def _finding(layer: str, key: str, cur: Any, base: Any, kind: str, note: str) -> dict[str, Any]:
    """Build a finding dict."""
    return {"layer": layer, "key": key, "current": cur, "baseline": base, "kind": kind, "note": note}


def render_report(measured: dict[str, dict[str, float]], findings: list[dict[str, Any]]) -> str:
    """Render a human-readable table of measured throughput plus violations."""
    lines = ["Per-layer performance scan", "=" * 70]
    for layer, metrics in sorted(measured.items()):
        lines.append(f"  {layer}:")
        for name, ops in sorted(metrics.items()):
            lines.append(f"    {name:<32} {ops:>12,.0f} ops/sec")
    lines.append("-" * 70)
    if not findings:
        lines.append("PASS: all layers within performance baseline.")
    else:
        lines.append(f"FAIL: {len(findings)} gate violation(s):")
        for f in findings:
            base = f"{f['baseline']:,.0f}" if isinstance(f["baseline"], (int, float)) else "n/a"
            lines.append(
                f"  [{f['kind']}] {f['layer']}.{f['key']} current={f['current']:,.0f} baseline={base} — {f['note']}"
            )
    return "\n".join(lines)


def emit_baseline(measured: dict[str, dict[str, float]]) -> str:
    """Emit a baseline YAML document for the current measured values."""
    doc = [
        "# Per-layer performance baseline (generated — do not hand-edit).",
        "# Regenerate: python scripts/py/perf_quality.py --baseline",
        "layers:",
    ]
    for layer, metrics in sorted(measured.items()):
        doc.append(f"  {layer}:")
        for name, ops in sorted(metrics.items()):
            doc.append(f"    {name}: {ops:.3f}")
    return "\n".join(doc) + "\n"


def main() -> int:
    """CLI entry: scan, compare, gate-verdict (or emit baseline)."""
    parser = argparse.ArgumentParser(description="Per-layer performance baseline scanner")
    parser.add_argument("--report", action="store_true", help="print the measured table only (no verdict)")
    parser.add_argument("--baseline", action="store_true", help="emit the current values as baseline YAML to stdout")
    parser.add_argument("--run-json", type=str, default="", help="dump measured values as JSON to a file")
    args = parser.parse_args()

    measured = measure_all()

    if args.baseline:
        print(emit_baseline(measured))
        return 0
    if args.run_json:
        Path(args.run_json).write_text(json.dumps(measured, indent=2), encoding="utf-8")
        return 0
    if args.report:
        print(render_report(measured, []))
        return 0

    baseline = load_baseline(BASELINE)
    if not baseline:
        print(f"perf_quality: baseline missing — run --baseline to generate {BASELINE}", file=sys.stderr)
        return 2
    findings = compare(measured, baseline)
    print(render_report(measured, findings))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
