# Quality Baseline — Per-Layer Metrics

Per-layer quality gates for the five-layer kernel: every layer (L1–L5) is
measured against a stored baseline by `scripts/py/layer_quality.py`, and the
scan fails the build when any hard gate is crossed or a soft gate drifts.

## Gate model

| Kind | Metric | Rule |
|------|--------|------|
| hard | `cjk_comment` | absolute red line — any CJK residue in comments fails |
| hard | `mega_funcs` (>200 lines) | absolute red line — any new mega-function fails |
| hard | `singleton_gaps` | absolute red line — unhandled singleton modules fail |
| soft | `missing_doc` / `short_doc` / `hardcoded_args` | monotonic — must never exceed baseline |
| soft | `large_funcs` (120–200 lines) | drift — allowed up to +20% of baseline |
| soft | `comment_ratio` | floor — must stay above 80% of baseline |

Baseline lives in `config/quality/layer-baseline.yaml` (generated, never
hand-edited). Regenerate with:

```bash
python scripts/py/layer_quality.py --baseline > config/quality/layer-baseline.yaml
```

## Current baseline (2026-08-18)

| Layer | Files | Lines | comment_ratio | mega>200 | large 120-200 | missDoc | shortDoc | hardc | cjk |
|-------|-------|-------|---------------|----------|---------------|---------|----------|-------|-----|
| L1 Kernel | 57 | 15,706 | 0.0385 | 0 | 0 | 0 | 1 | 1 | 0 |
| L2 Shell | 35 | 4,665 | 0.0151 | 0 | 0 | 0 | 0 | 3 | 0 |
| L3 Cell | 335 | 72,868 | 0.0327 | 0 | 6 | 0 | 0 | 17 | 0 |
| L4 Bridge | 107 | 22,115 | 0.0270 | 0 | 1 | 0 | 0 | 1 | 0 |
| L5 User | 2 | 599 | 0.0184 | 0 | 0 | 0 | 0 | 0 | 0 |

Numbers are snapshots — refresh with the scanner, never hand-edit.

## Usage

```bash
python scripts/py/layer_quality.py                # scan + gate verdict (exit 0/1/2)
python scripts/py/layer_quality.py --report       # measured table only
python scripts/py/layer_quality.py --baseline     # emit baseline YAML to stdout
```

`singleton_gaps` reuses `scripts/py/scan-singletons.py` and mirrors the
completeness-guard semantics in `tests/infra/test_resets_completeness.py`
(scanned − `_RESETS` − `KNOWN_GAPS`), so the two gates can never disagree.

## Integration

- Hard gates align with existing absolute red lines: `comment_audit.py
  --strict` (CJK) and `test_resets_completeness.py` (singletons).
- Soft gates ratchet: a baseline is a floor, not a target — metrics may only
  improve (monotonic) or stay within the drift band.
- CI wiring: `nightly.yml` runs `layer_quality.py` + `perf_quality.py`
  (quality-baselines job) so drift from the stored baselines fails CI.
  `verify-completion.sh` does NOT re-scan layers (it delegates to the
  dedicated checkers); local runs use the repo venv.
