## CompletionJudge effectiveness (auto-updated)

**Runs**: 171 | **COMPLETE**: 23 (13%) | **PARTIAL**: 21 (12%, fast mode — checks skipped) | **INCOMPLETE**: 127 (74%, machine 'not done')
**Mode split**: full 62 / fast 109 (fast = at least one check skipped)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 23 | 4 | 17% |
| 2026-08-19 | 22 | 10 | 45% |
| 2026-08-20 | 8 | 4 | 50% |
| 2026-08-21 | 4 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 107 (84% of incomplete)
- `delta`: 57 (45% of incomplete)
- `docs`: 43 (34% of incomplete)
- `lint`: 39 (31% of incomplete)
- `tests`: 20 (16% of incomplete)
- `singleton`: 16 (13% of incomplete)
- `coverage`: 15 (12% of incomplete)
- `complex`: 12 (9% of incomplete)
- `cycle`: 12 (9% of incomplete)
- `index`: 12 (9% of incomplete)
- `audit`: 9 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 158/167 (95%)
- `changelog`: 61/168 (36%)
- `complex`: 155/167 (93%)
- `coverage`: 47/62 (76%)
- `cycle`: 155/167 (93%)
- `delta`: 110/167 (66%)
- `docs`: 127/170 (75%)
- `index`: 155/167 (93%)
- `lint`: 131/170 (77%)
- `singleton`: 151/167 (90%)
- `tests`: 44/64 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.07 / 0.0 / 68.0
- `mega_funcs`: 3.0 / 15.82 / 0.0 / 256.0
- `net_delta`: 39.0 / 2651.17 / -4.0 / 27424.0
- `ruff_errors`: 6.0 / 2.78 / 2.0 / 6.0
- `tests_failed`: 2.0 / 1.2 / 1.0 / 2.0
- `tests_passed`: 4925.0 / 4767.19 / 4583.0 / 4925.0
