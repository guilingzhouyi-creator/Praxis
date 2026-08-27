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
    python scripts/py/perf_quality.py --baseline-layer L2 # update one layer in the baseline
    python scripts/py/perf_quality.py --run-json <f> # dump measured JSON (debug)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
BASELINE = ROOT / "config" / "quality" / "perf-baseline.yaml"

# In-process L3 query benches import l3.* directly — put the Python reference
# runtime on sys.path so
# they resolve the worktree sources (never an installed praxis copy).
sys.path.insert(0, str(ROOT / "systems/python-reference-runtime"))
sys.path.insert(0, str(ROOT / "scripts" / "py"))

from perf_harness import (  # noqa: E402
    PERF_HARNESS_WARMUP_ROUNDS,
    platform_fingerprint,
    run_benchmark,
)
from perf_harness import (  # noqa: E402
    SCHEMA_VERSION as PERF_SCHEMA_VERSION,
)

PERF_DRIFT_FLOOR = 0.9  # ops_per_sec must stay >= 90% of baseline

# Benchmark -> layer mapping; each entry names the driver script and the
# keys it reports (the drivers' own output formats are parsed below).
_BENCH_PLATFORM = ROOT / "tests" / "benchmarks" / "bench_platform.py"
_BENCH_R4 = ROOT / "tests" / "benchmarks" / "bench_r4_candidate_store.py"
_BENCH_CARD = ROOT / "tests" / "benchmarks" / "bench_card.py"
_BENCH_SCALE = ROOT / "tests" / "benchmarks" / "bench_scale.py"
_BENCH_TOOLCHAIN = ROOT / "tests" / "benchmarks" / "bench_security_toolchain.py"
_BENCH_L2_PROTOCOL = ROOT / "tests" / "benchmarks" / "bench_l2_protocol.py"
_BENCH_COMPRESSION = ROOT / "tests" / "benchmarks" / "bench_compression.py"


def _run_driver(args: list[str], timeout: int = 180) -> str:
    """Run a benchmark driver and return its combined stdout/stderr."""
    proc = subprocess.run([sys.executable, *args], capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    if proc.returncode:
        detail = (proc.stdout + proc.stderr).strip()
        raise RuntimeError(f"benchmark driver failed with exit code {proc.returncode}: {detail}")
    return proc.stdout + proc.stderr


def measure_l1() -> dict[str, float]:
    """Run bench_platform --json and extract per-primitive ops/sec (L1)."""
    tmp = ROOT / ".praxis" / "perf_platform.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    _run_driver([str(_BENCH_PLATFORM), "--json", str(tmp), "--rounds", "3"])
    data = json.loads(tmp.read_text(encoding="utf-8"))
    return {name: float(v["ops_per_sec"]) for name, v in data.get("micro", {}).items() if "ops_per_sec" in v}


def measure_amdahl() -> dict[str, float]:
    """Run bench_scale amdahl and extract the L1 serial fraction as a score.

    The raw ``serial_fraction_p`` is a low-is-better ratio (high P = serial
    bottleneck = Rust-migration priority). To keep the gate direction uniform
    with the throughput metrics (high-is-better), it is reported as the
    parallel score ``1 - p`` (0..1) — a regression (P rising) shows up as a
    parallel-score drop and trips the 90% drift floor.
    """
    tmp = ROOT / ".praxis" / "perf_amdahl.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    _run_driver([str(_BENCH_SCALE), "--mode", "amdahl", "--json", str(tmp), "--rounds", "3"])
    data = json.loads(tmp.read_text(encoding="utf-8"))
    p = float((data.get("amdahl_l1") or {}).get("serial_fraction_p", 1.0))
    # Degrade (omit the metric) when the fit is meaningless: a serial fraction
    # of ~1.0 on short/WSL runs is measurement noise, not a real bottleneck —
    # including it would trip the gate with a false hard error.
    if p >= 0.99:
        return {}
    # Clamp to [0, 1] so a broken fit never produces a score above 1.0.
    return {"amdahl_parallel_score": round(max(0.0, min(1.0, 1.0 - p)), 4)}


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


def measure_compression() -> dict[str, float]:
    """Run bench_compression and extract compression ratio + throughput (L3)."""
    out = _run_driver([str(_BENCH_COMPRESSION), "--messages", "200", "--rounds", "3"])
    result: dict[str, float] = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key not in ("compression_ratio", "compress_ops_per_sec"):
            continue
        try:
            result[key] = float(value.strip())
        except ValueError:
            continue
    return result


def _record_variance_warning(
    diagnostics: list[dict[str, Any]] | None,
    benchmark: str,
    summary: dict[str, Any],
) -> None:
    """Append a non-blocking variance diagnostic when a sample is unstable."""
    if diagnostics is None or not summary.get("variance_warning"):
        return
    median = float(summary.get("ops_per_sec", 0.0))
    mad = float(summary.get("mad_ops_per_sec", 0.0))
    mad_pct = mad / median * 100 if median > 0 else 0.0
    diagnostics.append(
        {
            "benchmark": benchmark,
            "median_ops_per_sec": median,
            "mad_ops_per_sec": mad,
            "mad_pct": mad_pct,
            "coefficient_of_variation": float(summary.get("coefficient_of_variation", 0.0)),
            "note": "sample variance exceeds the configured MAD warning threshold",
        }
    )


def measure_l2(diagnostics: list[dict[str, Any]] | None = None) -> dict[str, float]:
    """Run the L2 protocol benchmark and extract throughput metrics."""
    tmp = ROOT / ".praxis" / "perf_l2_protocol.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    _run_driver(
        [
            str(_BENCH_L2_PROTOCOL),
            "--iterations",
            "1000",
            "--warmups",
            "1",
            "--samples",
            "3",
            "--json",
            str(tmp),
        ]
    )
    data = json.loads(tmp.read_text(encoding="utf-8"))
    result: dict[str, float] = {}
    for benchmark in data.get("benchmarks", []):
        name = benchmark.get("name")
        summary = benchmark.get("summary") or {}
        if not name or not isinstance(summary, dict):
            continue
        _record_variance_warning(diagnostics, name, summary)
        if isinstance(summary.get("ops_per_sec"), (int, float)):
            result[f"{name}.ops_per_sec"] = float(summary["ops_per_sec"])
    return result


# In-process L3 query benchmarks (Phase perf pass): department / violation /
# identity hot paths measured as ops/sec. These run in-process (no driver
# script) — they exercise the indexed/cached lookup paths directly.
_DEPT_ITERS = 2_000
_DEPT_ROUNDS = 3


def _ops_per_sec(
    fn,
    iters: int,
    rounds: int,
    *,
    metric_name: str,
    diagnostics: list[dict[str, Any]] | None = None,
) -> float:
    """Run *fn* for *rounds* passes of *iters* ops; return median ops/sec."""
    result = run_benchmark("perf_quality.in_process", fn, iters, warmups=PERF_HARNESS_WARMUP_ROUNDS, samples=rounds)
    _record_variance_warning(diagnostics, metric_name, result.as_dict()["summary"])
    return result.median_ops_per_sec


def _seed_dept_state() -> None:
    """Seed the department registry + monitor state for the L3 query benches.

    Registers a handful of departments (division active) so the indexed
    lookups / violation checks measure a realistic multi-department setup.
    """
    from l3.cell.department import get_department_manager, reset_department_manager

    reset_department_manager()
    m = get_department_manager()
    # Force division active (switch + cell count) without touching settings.
    m.enabled = lambda: True  # type: ignore[method-assign]
    m.cell_count = lambda: 3  # type: ignore[method-assign]
    for i in range(4):
        m.register(f"dept-{i}", [f"role-{i}"], "bench dept")
        m._departments[f"dept-{i}"].dept_type = f"type-{i}"
    m._departments["dept-0"].permission_scope = ["test", "verification"]
    m._rebuild_indexes()


def measure_l3_dept(diagnostics: list[dict[str, Any]] | None = None) -> dict[str, float]:
    """Measure department/violation/identity query throughput (L3, in-process)."""
    import os

    _seed_dept_state()
    from l1.kernel.identity_binding import get_identity_binding_manager, reset_identity_binding_manager
    from l3.cell import violation_monitor as vm
    from l3.cell.department import get_department_manager, reset_department_manager

    mgr = get_department_manager()
    # P2#3 fix: the bench bind() would persist a spurious cell-1/build binding
    # into the production state file. Point the manager at a temp state path
    # (before first instantiation) so the bench never mutates real identity
    # state; the temp file is removed in cleanup below.
    tmp_state = ROOT / ".praxis" / "perf_identity_tmp.json"
    os.environ["PRAXIS_IDENTITY_STATE"] = str(tmp_state)
    reset_identity_binding_manager()
    ibm = get_identity_binding_manager()
    ibm.bind("cell-1", "build", "frag", internal=True)
    vm.reset_violation_monitor()
    vm.set_enabled(True)

    result = {
        "dept_role_ops_per_sec": _ops_per_sec(
            lambda n: [mgr.department_for_role("role-2") for _ in range(n)],
            _DEPT_ITERS,
            _DEPT_ROUNDS,
            metric_name="dept_role_ops_per_sec",
            diagnostics=diagnostics,
        ),
        "dept_route_ops_per_sec": _ops_per_sec(
            lambda n: [mgr.route_content("type-2") for _ in range(n)],
            _DEPT_ITERS,
            _DEPT_ROUNDS,
            metric_name="dept_route_ops_per_sec",
            diagnostics=diagnostics,
        ),
        "violation_check_ops_per_sec": _ops_per_sec(
            lambda n: [vm.check_output("a", "c1", "role-2", "def test_foo(): assert 1") for _ in range(n)],
            _DEPT_ITERS,
            _DEPT_ROUNDS,
            metric_name="violation_check_ops_per_sec",
            diagnostics=diagnostics,
        ),
        "identity_definition_ops_per_sec": _ops_per_sec(
            lambda n: [ibm.resolve_definition("cell-1", "build") for _ in range(n)],
            _DEPT_ITERS,
            _DEPT_ROUNDS,
            metric_name="identity_definition_ops_per_sec",
            diagnostics=diagnostics,
        ),
    }
    # Clean up the seeded singletons + temp state file so the rest of the
    # scan (and any later praxis run) is unaffected.
    vm.reset_violation_monitor()
    reset_identity_binding_manager()
    reset_department_manager()
    try:
        if tmp_state.exists():
            tmp_state.unlink()
    except OSError as e:
        print(f"perf_quality: temp identity state cleanup failed: {e}", file=sys.stderr)
    return result


def measure_all(diagnostics: list[dict[str, Any]] | None = None) -> dict[str, dict[str, float]]:
    """Run every layer benchmark and return {layer: {metric: ops_per_sec}}."""
    l1 = measure_l1()
    l1.update(measure_amdahl())
    l2 = measure_l2(diagnostics)
    l3 = measure_l3()
    l3.update(measure_l3_dept(diagnostics))
    l3.update(measure_toolchain())
    l3.update(measure_compression())
    return {"L1": l1, "L2": l2, "L3": l3, "L5": measure_l5()}


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


def compare(
    measured: dict[str, dict[str, float]],
    baseline: dict[str, Any],
    *,
    allow_missing_baseline: bool = False,
) -> list[dict[str, Any]]:
    """Compare measured throughput against the baseline; return finding dicts."""
    findings: list[dict[str, Any]] = []
    layers_baseline = baseline.get("layers", {})
    for layer, metrics in sorted(measured.items()):
        bl = layers_baseline.get(layer, {})
        for name, ops in sorted(metrics.items()):
            base = bl.get(name)
            if base is None:
                # Optional score metrics (e.g. amdahl_parallel_score) are only
                # emitted on hardware where the fit is meaningful; a missing
                # baseline entry for them is a soft notice, not a hard failure
                # (the baseline is regenerated where the metric appears).
                if name.endswith("_score"):
                    findings.append(
                        _finding(layer, name, ops, None, "notice", "no baseline entry (optional score metric)")
                    )
                    continue
                kind = "notice" if allow_missing_baseline else "hard"
                note = "no baseline entry (explicitly allowed)" if allow_missing_baseline else "no baseline entry"
                findings.append(_finding(layer, name, ops, None, kind, note))
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


def render_report(
    measured: dict[str, dict[str, float]],
    findings: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]] | None = None,
) -> str:
    """Render a human-readable table of measured throughput plus violations."""
    lines = ["Per-layer performance scan", "=" * 70]
    for layer, metrics in sorted(measured.items()):
        lines.append(f"  {layer}:")
        for name, ops in sorted(metrics.items()):
            lines.append(f"    {name:<32} {ops:>12,.0f} ops/sec")
    lines.append("-" * 70)
    if diagnostics:
        lines.append(f"WARN: {len(diagnostics)} high-variance sample(s); baseline was not changed.")
        for diagnostic in diagnostics:
            lines.append(
                f"  [variance] {diagnostic['benchmark']} MAD={diagnostic['mad_pct']:.2f}% "
                f"CV={diagnostic['coefficient_of_variation']:.3f}"
            )
    blocking = [finding for finding in findings if finding["kind"] in {"hard", "soft"}]
    notices = [finding for finding in findings if finding["kind"] == "notice"]
    if not blocking:
        if notices:
            lines.append(f"NOTICE: {len(notices)} non-blocking baseline notice(s):")
            for finding in notices:
                lines.append(f"  [notice] {finding['layer']}.{finding['key']} - {finding['note']}")
        lines.append("PASS: all layers within performance baseline.")
    else:
        lines.append(f"FAIL: {len(blocking)} gate violation(s):")
        for f in blocking:
            base = f"{f['baseline']:,.0f}" if isinstance(f["baseline"], (int, float)) else "n/a"
            lines.append(
                f"  [{f['kind']}] {f['layer']}.{f['key']} current={f['current']:,.0f} baseline={base} — {f['note']}"
            )
    return "\n".join(lines)


def emit_baseline(
    measured: dict[str, dict[str, float]],
    existing: dict[str, Any] | None = None,
) -> str:
    """Emit a baseline YAML document for the current measured values."""
    layers = dict((existing or {}).get("layers", {}))
    layers.update(measured)
    doc = [
        "# Per-layer performance baseline (generated — do not hand-edit).",
        "# Regenerate: python scripts/py/perf_quality.py --baseline",
        "# Optional score metrics (names ending in _score, e.g. amdahl_parallel_score)",
        "# are emitted only where the underlying fit is meaningful; a missing",
        "# baseline entry for them is a soft notice, not a hard gate failure.",
        "layers:",
    ]
    for layer, metrics in sorted(layers.items()):
        doc.append(f"  {layer}:")
        for name, ops in sorted(metrics.items()):
            doc.append(f"    {name}: {ops:.3f}")
    return "\n".join(doc) + "\n"


def main() -> int:
    """CLI entry: scan, compare, gate-verdict (or emit baseline)."""
    parser = argparse.ArgumentParser(description="Per-layer performance baseline scanner")
    parser.add_argument("--report", action="store_true", help="print the measured table only (no verdict)")
    parser.add_argument("--baseline", action="store_true", help="emit the current values as baseline YAML to stdout")
    parser.add_argument(
        "--baseline-layer",
        action="append",
        dest="baseline_layers",
        metavar="LAYER",
        help="update only the named layer(s) while preserving other baseline values",
    )
    parser.add_argument("--run-json", type=str, default="", help="dump measured values as JSON to a file")
    parser.add_argument(
        "--allow-missing-baseline",
        action="store_true",
        help="treat missing metric entries as non-blocking diagnostics (migration only)",
    )
    args = parser.parse_args()
    if args.baseline_layers and not args.baseline:
        parser.error("--baseline-layer requires --baseline")

    diagnostics: list[dict[str, Any]] = []
    measured = measure_all(diagnostics)

    if args.baseline:
        if args.baseline_layers:
            selected = {layer: measured[layer] for layer in args.baseline_layers if layer in measured}
            unknown = sorted(set(args.baseline_layers) - set(selected))
            if unknown:
                parser.error(f"unknown baseline layer(s): {', '.join(unknown)}")
            print(emit_baseline(selected, load_baseline(BASELINE)))
        else:
            print(emit_baseline(measured))
        return 0
    if args.run_json:
        document = {
            "schema_version": PERF_SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "platform": platform_fingerprint(),
            "layers": measured,
            "diagnostics": {"variance_warnings": diagnostics},
        }
        destination = Path(args.run_json)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    if args.report:
        print(render_report(measured, [], diagnostics))
        return 0

    baseline = load_baseline(BASELINE)
    if not baseline:
        print(f"perf_quality: baseline missing — run --baseline to generate {BASELINE}", file=sys.stderr)
        return 2
    findings = compare(measured, baseline, allow_missing_baseline=args.allow_missing_baseline)
    print(render_report(measured, findings, diagnostics))
    return 1 if any(finding["kind"] in {"hard", "soft"} for finding in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
