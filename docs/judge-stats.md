## CompletionJudge effectiveness (auto-updated)

**Runs**: 205 | **COMPLETE**: 32 (16%) | **PARTIAL**: 23 (11%, fast mode — checks skipped) | **INCOMPLETE**: 150 (73%, machine 'not done')
**Mode split**: full 86 / fast 119 (fast = at least one check skipped)

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
| 2026-08-22 | 17 | 5 | 29% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 125 (83% of incomplete)
- `delta`: 67 (45% of incomplete)
- `lint`: 51 (34% of incomplete)
- `docs`: 49 (33% of incomplete)
- `tests`: 28 (19% of incomplete)
- `coverage`: 24 (16% of incomplete)
- `audit`: 17 (11% of incomplete)
- `singleton`: 16 (11% of incomplete)
- `cycle`: 13 (9% of incomplete)
- `complex`: 12 (8% of incomplete)
- `index`: 12 (8% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 184/201 (92%)
- `changelog`: 77/202 (38%)
- `complex`: 189/201 (94%)
- `coverage`: 62/86 (72%)
- `cycle`: 188/201 (94%)
- `delta`: 134/201 (67%)
- `docs`: 155/204 (76%)
- `index`: 189/201 (94%)
- `lint`: 153/204 (75%)
- `singleton`: 185/201 (92%)
- `tests`: 60/88 (68%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.86 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 13.51 / 0.0 / 256.0
- `net_delta`: 168.0 / 2348.39 / -4.0 / 27424.0
- `ruff_errors`: 3.0 / 2.77 / 2.0 / 6.0
- `tests_failed`: 1.0 / 1.7 / 1.0 / 7.0
- `tests_passed`: 4920.0 / 4841.18 / 4583.0 / 5065.0
