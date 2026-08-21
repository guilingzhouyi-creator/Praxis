## CompletionJudge effectiveness (auto-updated)

**Runs**: 187 | **COMPLETE**: 27 (14%) | **PARTIAL**: 22 (12%, fast mode — checks skipped) | **INCOMPLETE**: 138 (74%, machine 'not done')
**Mode split**: full 74 / fast 113 (fast = at least one check skipped)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 23 | 4 | 17% |
| 2026-08-19 | 22 | 10 | 45% |
| 2026-08-20 | 8 | 4 | 50% |
| 2026-08-21 | 20 | 4 | 20% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 115 (83% of incomplete)
- `delta`: 60 (43% of incomplete)
- `docs`: 49 (36% of incomplete)
- `lint`: 46 (33% of incomplete)
- `tests`: 27 (20% of incomplete)
- `coverage`: 22 (16% of incomplete)
- `singleton`: 16 (12% of incomplete)
- `cycle`: 13 (9% of incomplete)
- `audit`: 13 (9% of incomplete)
- `complex`: 12 (9% of incomplete)
- `index`: 12 (9% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 170/183 (93%)
- `changelog`: 69/184 (38%)
- `complex`: 171/183 (93%)
- `coverage`: 52/74 (70%)
- `cycle`: 170/183 (93%)
- `delta`: 123/183 (67%)
- `docs`: 137/186 (74%)
- `index`: 171/183 (93%)
- `lint`: 140/186 (75%)
- `singleton`: 167/183 (91%)
- `tests`: 49/76 (64%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 69.0 / 66.6 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 14.62 / 0.0 / 256.0
- `net_delta`: 8.0 / 2565.19 / -4.0 / 27424.0
- `ruff_errors`: 2.0 / 2.7 / 2.0 / 6.0
- `tests_failed`: 7.0 / 1.73 / 1.0 / 7.0
- `tests_passed`: 5065.0 / 4817.96 / 4583.0 / 5065.0
