# Performance Baseline — Per-Layer Throughput Gates

Runtime complement to `quality-baseline.md` (structural quality): every layer's
benchmark primitives are measured by `scripts/py/perf_quality.py` against a
stored baseline in `config/quality/perf-baseline.yaml`.

## Layer mapping

| Layer | Benchmark driver | Metrics |
|-------|------------------|---------|
| L1 | `tests/benchmarks/bench_platform.py --json` | `mutex.acquire_release`, `event_bus.emit`, `channel.put_get`, `worker_pool.submit`, `thread.create_join` (ops/sec) |
| L3 | `tests/benchmarks/bench_r4_candidate_store.py` | `submit_ops_per_sec`, `durable_ops_per_sec` (candidate-ledger ingestion) |
| L5 | `tests/benchmarks/bench_card.py` | `card.steps_per_sec` (end-to-end card throughput) |

## Gate model

| Kind | Rule |
|------|------|
| hard | benchmark errors or is unavailable — fails the run |
| soft (drift) | `ops_per_sec` must stay above **90%** of baseline (same 10% regression line as `.github/workflows/benchmark.yml`) |

Baseline lives in `config/quality/perf-baseline.yaml` (generated, never
hand-edited). Regenerate with:

```bash
python scripts/py/perf_quality.py --baseline > config/quality/perf-baseline.yaml
```

## Usage

```bash
python scripts/py/perf_quality.py                # scan + gate verdict (exit 0/1/2)
python scripts/py/perf_quality.py --report       # measured table only
python scripts/py/perf_quality.py --baseline     # emit baseline YAML to stdout
python scripts/py/perf_quality.py --run-json <f> # dump measured JSON (debug)
make quality-all                                  # structural + performance gates in one run
```

## Environment sensitivity

WSL/shared runners show ±30% load swings (documented in `benchmark.yml`), so a
single scan may report soft-drift findings against a baseline captured under a
different load. The drift floor is the CI hard line on dedicated runners; for
local scans, regenerate the baseline on the same environment before judging.

## Integration

- `perf_quality.py` mirrors the `layer_quality.py` gate shape (hard red lines +
  soft drift, identical report format), so both are consumed the same way.
- `make quality-all` runs both scanners sequentially — structural quality then
  runtime performance — as the unified per-layer quality gate.
- The L1 micro-primitive baselines feed the Rust-sink readiness evaluation
  (see `frontend-kernel-roadmap.md` M3): throughput per primitive on the target
  platform is the evidence for hot-path migration priority.
