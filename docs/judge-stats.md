## CompletionJudge effectiveness (auto-updated)

**Runs**: 168 | **COMPLETE**: 23 (14%) | **PARTIAL**: 21 (12%, fast mode — checks skipped) | **INCOMPLETE**: 124 (74%, machine 'not done')
**Mode split**: full 61 / fast 107 (fast = at least one check skipped)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 23 | 4 | 17% |
| 2026-08-19 | 22 | 10 | 45% |
| 2026-08-20 | 8 | 4 | 50% |
| 2026-08-21 | 1 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 104 (84% of incomplete)
- `delta`: 55 (44% of incomplete)
- `docs`: 40 (32% of incomplete)
- `lint`: 36 (29% of incomplete)
- `tests`: 19 (15% of incomplete)
- `singleton`: 15 (12% of incomplete)
- `coverage`: 14 (11% of incomplete)
- `complex`: 11 (9% of incomplete)
- `cycle`: 11 (9% of incomplete)
- `index`: 11 (9% of incomplete)
- `audit`: 6 (5% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 158/164 (96%)
- `changelog`: 61/165 (37%)
- `complex`: 153/164 (93%)
- `coverage`: 47/61 (77%)
- `cycle`: 153/164 (93%)
- `delta`: 109/164 (66%)
- `docs`: 127/167 (76%)
- `index`: 153/164 (93%)
- `lint`: 131/167 (78%)
- `singleton`: 149/164 (91%)
- `tests`: 44/63 (70%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.07 / 0.0 / 68.0
- `mega_funcs`: 3.0 / 14.4 / 0.0 / 211.0
- `net_delta`: 805.0 / 2710.19 / -4.0 / 27424.0
- `ruff_errors`: 6.0 / 2.78 / 2.0 / 6.0
- `tests_failed`: 2.0 / 1.2 / 1.0 / 2.0
- `tests_passed`: 4925.0 / 4767.19 / 4583.0 / 4925.0
