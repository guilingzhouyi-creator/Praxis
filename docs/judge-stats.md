## CompletionJudge effectiveness (auto-updated)

**Runs**: 229 | **COMPLETE**: 34 (15%) | **PARTIAL**: 36 (16%, fast mode — checks skipped) | **INCOMPLETE**: 159 (69%, machine 'not done')
**Mode split**: full 91 / fast 138 (fast = at least one check skipped)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 23 | 4 | 17% |
| 2026-08-19 | 22 | 10 | 45% |
| 2026-08-20 | 8 | 4 | 50% |
| 2026-08-21 | 21 | 4 | 19% |
| 2026-08-22 | 34 | 7 | 21% |
| 2026-08-23 | 7 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 134 (84% of incomplete)
- `delta`: 71 (45% of incomplete)
- `lint`: 53 (33% of incomplete)
- `docs`: 52 (33% of incomplete)
- `tests`: 29 (18% of incomplete)
- `coverage`: 25 (16% of incomplete)
- `audit`: 18 (11% of incomplete)
- `singleton`: 16 (10% of incomplete)
- `cycle`: 13 (8% of incomplete)
- `complex`: 12 (8% of incomplete)
- `index`: 12 (8% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 194/212 (92%)
- `changelog`: 79/213 (37%)
- `complex`: 200/212 (94%)
- `coverage`: 66/91 (73%)
- `cycle`: 199/212 (94%)
- `delta`: 141/212 (67%)
- `docs`: 163/215 (76%)
- `index`: 200/212 (94%)
- `lint`: 162/215 (75%)
- `singleton`: 196/212 (92%)
- `tests`: 64/93 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.93 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 12.92 / 0.0 / 256.0
- `net_delta`: 1.0 / 2265.15 / -4.0 / 27424.0
- `ruff_errors`: 3.0 / 2.79 / 2.0 / 6.0
- `tests_failed`: 1.0 / 1.67 / 1.0 / 7.0
- `tests_passed`: 4964.0 / 4847.51 / 4583.0 / 5065.0
