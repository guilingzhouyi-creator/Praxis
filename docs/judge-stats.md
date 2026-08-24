## CompletionJudge effectiveness (auto-updated)

**Runs**: 219 | **COMPLETE**: 34 (16%) | **PARTIAL**: 22 (10%, fast mode — checks skipped) | **INCOMPLETE**: 163 (74%, machine 'not done')
**Mode split**: full 91 / fast 128 (fast = at least one check skipped)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 22 | 4 | 18% |
| 2026-08-19 | 22 | 10 | 45% |
| 2026-08-20 | 8 | 4 | 50% |
| 2026-08-21 | 21 | 4 | 19% |
| 2026-08-22 | 25 | 7 | 28% |
| 2026-08-23 | 5 | 0 | 0% |
| 2026-08-24 | 2 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 138 (85% of incomplete)
- `delta`: 72 (44% of incomplete)
- `lint`: 56 (34% of incomplete)
- `docs`: 52 (32% of incomplete)
- `tests`: 29 (18% of incomplete)
- `coverage`: 25 (15% of incomplete)
- `audit`: 19 (12% of incomplete)
- `singleton`: 16 (10% of incomplete)
- `cycle`: 13 (8% of incomplete)
- `complex`: 12 (7% of incomplete)
- `index`: 12 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 197/216 (91%)
- `changelog`: 79/217 (36%)
- `complex`: 204/216 (94%)
- `coverage`: 66/91 (73%)
- `cycle`: 203/216 (94%)
- `delta`: 144/216 (67%)
- `docs`: 167/219 (76%)
- `index`: 204/216 (94%)
- `lint`: 163/219 (74%)
- `singleton`: 200/216 (93%)
- `tests`: 64/93 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.93 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 12.73 / 0.0 / 256.0
- `net_delta`: 1041.0 / 2254.31 / -4.0 / 27424.0
- `ruff_errors`: 2.0 / 2.65 / 2.0 / 6.0
- `tests_failed`: 1.0 / 1.67 / 1.0 / 7.0
- `tests_passed`: 4964.0 / 4847.51 / 4583.0 / 5065.0
