## CompletionJudge effectiveness (auto-updated)

**Runs**: 220 | **COMPLETE**: 34 (15%) | **PARTIAL**: 30 (14%, fast mode — checks skipped) | **INCOMPLETE**: 156 (71%, machine 'not done')
**Mode split**: full 91 / fast 129 (fast = at least one check skipped)

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
| 2026-08-22 | 32 | 7 | 22% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 131 (84% of incomplete)
- `delta`: 69 (44% of incomplete)
- `lint`: 53 (34% of incomplete)
- `docs`: 52 (33% of incomplete)
- `tests`: 29 (19% of incomplete)
- `coverage`: 25 (16% of incomplete)
- `audit`: 18 (12% of incomplete)
- `singleton`: 16 (10% of incomplete)
- `cycle`: 13 (8% of incomplete)
- `complex`: 12 (8% of incomplete)
- `index`: 12 (8% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 191/209 (91%)
- `changelog`: 79/210 (38%)
- `complex`: 197/209 (94%)
- `coverage`: 66/91 (73%)
- `cycle`: 196/209 (94%)
- `delta`: 140/209 (67%)
- `docs`: 160/212 (75%)
- `index`: 197/209 (94%)
- `lint`: 159/212 (75%)
- `singleton`: 193/209 (92%)
- `tests`: 64/93 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.93 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 13.08 / 0.0 / 256.0
- `net_delta`: 532.0 / 2294.29 / -4.0 / 27424.0
- `ruff_errors`: 3.0 / 2.79 / 2.0 / 6.0
- `tests_failed`: 1.0 / 1.67 / 1.0 / 7.0
- `tests_passed`: 4964.0 / 4847.51 / 4583.0 / 5065.0
