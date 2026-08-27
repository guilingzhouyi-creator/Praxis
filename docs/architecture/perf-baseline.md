# Performance Baseline — Per-Layer Throughput Gates

Runtime complement to `quality-baseline.md` (structural quality): every layer's
benchmark primitives are measured by `scripts/py/bench_layer_runtime.py` against a
stored baseline in `config/quality/perf-baseline.yaml`.

## Layer mapping

| Layer | Benchmark driver | Metrics |
|-------|------------------|---------|
| L1 | `tests/benchmarks/bench_platform.py --json` | `mutex.acquire_release`, `event_bus.emit`, `channel.put_get`, `worker_pool.submit`, `thread.create_join` (ops/sec) |
| L2 | `tests/benchmarks/bench_l2_protocol.py` | envelope encode/decode and JSONL host command dispatch (ops/sec + p95 batch latency) |
| L3 | `tests/benchmarks/bench_r4_candidate_store.py` | `submit_ops_per_sec`, `durable_ops_per_sec` (candidate-ledger ingestion) |
| L3 | `tests/benchmarks/bench_security_toolchain.py` | DVG planning/registration, TODO persistence, R5 rule/semantic edges, evidence append/verify (ops/sec) |
| L5 | `tests/benchmarks/bench_card.py` | `card.steps_per_sec` (end-to-end card throughput) |

## Gate model

| Kind | Rule |
|------|------|
| hard | benchmark errors or is unavailable — fails the run |
| soft (drift) | `ops_per_sec` must stay above **90%** of baseline (same 10% regression line as `.github/workflows/benchmark.yml`) |

Baseline lives in `config/quality/perf-baseline.yaml` (generated, never
hand-edited). Regenerate with:

```bash
python scripts/py/bench_layer_runtime.py --baseline > config/quality/perf-baseline.yaml
```

## Unified metric contract

Runtime measurements from the security/toolchain cross-links are emitted to
`StatsCenter` through `systems/python-reference-runtime/l3/services/observability.py`. Duration values use
the `*.duration_ms` suffix; volume values use `*.count`, `*.nodes`,
`*.records`, `*.edges`, or `*.tasks`; benchmark drivers expose the comparable
`*_ops_per_sec` values. New points use bounded dimensions only:
`cell`, `agent`, `card`, `tool`, `mode`, `edge_mode`, `source`, `success`,
`status`, `phase`, and `relation`. Evidence payloads and target URLs remain
out of metric tags. Ingestion is best-effort and never changes the protected
execution path.

The current namespaces are:

- `tool_registry.*` and `dvg.*` for config-driven registration and dependency planning;
- `todo.*` for JSON persistence and register-backed executor/card/skill indexes;
- `r5.*` for rule supply and bounded hybrid semantic extraction;
- `security_evidence.*` for append, sidecar metadata, and fixity verification;
- `attack_tool.*` for posture-gated tool latency and outcomes.

`bench_layer_runtime.py` includes the security/toolchain driver in the L3 gate and
applies the same 90% drift floor as every existing layer baseline.

## Sampling contract

`config/quality/perf-schema.json` is the machine-readable result contract and
`scripts/py/_lib/perf_sampling.py` is the shared sampler for in-process benchmarks.
Sampling policy is declared in `config/quality/perf-harness.yaml` and validated
at load time; it is no longer a runtime `l1.kernel.params` dependency. The
shipped policy discards one warmup round and records seven samples by default.
The sampler emits a versioned document containing platform metadata,
per-sample throughput, average operation latency, p95 batch latency, median
absolute deviation (MAD), and coefficient of variation (CV).
`bench_layer_runtime.py --run-json` wraps the layer measurements in the same schema
with `schema_version`, `generated_at`, `platform`, and `layers` fields.

The sampler treats variance as evidence, not as a reason to silently rewrite a
baseline. Baselines are regenerated only on the same platform and dependency
set after a stable run; local WSL measurements remain diagnostic when they
diverge from a dedicated CI baseline.

Missing baseline entries are blocking by default. During an intentional metric
migration, `--allow-missing-baseline` converts those entries into visible,
non-blocking notices; it never changes the stored file. A stable layer can be
promoted without rewriting unrelated layers:

```bash
python tests/benchmarks/bench_l2_protocol.py --iterations 5000 --warmups 3 --samples 31 \
  --json .praxis/l2-continuous.json
python scripts/py/bench_layer_runtime.py --baseline --baseline-layer L2 > /tmp/praxis-perf-baseline.yaml
mv /tmp/praxis-perf-baseline.yaml config/quality/perf-baseline.yaml
```

The layer-scoped command preserves existing values and only replaces the
selected layer after the operator has reviewed the repeated-sample report.

## Usage

```bash
python scripts/py/bench_layer_runtime.py                # scan + gate verdict (exit 0/1/2)
python scripts/py/bench_layer_runtime.py --report       # measured table only
python scripts/py/bench_layer_runtime.py --baseline     # emit baseline YAML to stdout
python scripts/py/bench_layer_runtime.py --run-json <f> # dump measured JSON (debug)
make quality-all                                  # structural + performance gates in one run
```

## Environment sensitivity

WSL/shared runners show ±30% load swings (documented in `benchmark.yml`), so a
single scan may report soft-drift findings against a baseline captured under a
different load. The drift floor is the CI hard line on dedicated runners; for
local scans, regenerate the baseline on the same environment before judging.

## Integration

- `bench_layer_runtime.py` mirrors the `bench_layer_structure.py` gate shape (hard red lines +
  soft drift, identical report format), so both are consumed the same way.
- `make quality-all` runs both scanners sequentially — structural quality then
  runtime performance — as the unified per-layer quality gate.
- The L1 micro-primitive baselines feed the Rust-sink readiness evaluation
  (see `frontend-kernel-roadmap.md` M3): throughput per primitive on the target
  platform is the evidence for hot-path migration priority.
