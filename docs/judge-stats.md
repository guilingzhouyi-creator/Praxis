## CompletionJudge effectiveness (auto-updated)

**Runs**: 196 | **COMPLETE**: 29 (15%) | **PARTIAL**: 22 (11%, fast mode — checks skipped) | **INCOMPLETE**: 145 (74%, machine 'not done')
**Mode split**: full 79 / fast 117 (fast = at least one check skipped)

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
| 2026-08-22 | 8 | 2 | 25% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 120 (83% of incomplete)
- `delta`: 65 (45% of incomplete)
- `lint`: 50 (34% of incomplete)
- `docs`: 49 (34% of incomplete)
- `tests`: 27 (19% of incomplete)
- `coverage`: 22 (15% of incomplete)
- `singleton`: 16 (11% of incomplete)
- `audit`: 16 (11% of incomplete)
- `cycle`: 13 (9% of incomplete)
- `complex`: 12 (8% of incomplete)
- `index`: 12 (8% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 176/192 (92%)
- `changelog`: 73/193 (38%)
- `complex`: 180/192 (94%)
- `coverage`: 57/79 (72%)
- `cycle`: 179/192 (93%)
- `delta`: 127/192 (66%)
- `docs`: 146/195 (75%)
- `index`: 180/192 (94%)
- `lint`: 145/195 (74%)
- `singleton`: 176/192 (92%)
- `tests`: 54/81 (67%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.74 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 14.03 / 0.0 / 256.0
- `net_delta`: 79.0 / 2423.87 / -4.0 / 27424.0
- `ruff_errors`: 3.0 / 2.77 / 2.0 / 6.0
- `tests_failed`: 7.0 / 1.73 / 1.0 / 7.0
- `tests_passed`: 4920.0 / 4830.56 / 4583.0 / 5065.0
