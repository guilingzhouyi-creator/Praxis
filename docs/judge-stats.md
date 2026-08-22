## CompletionJudge effectiveness (auto-updated)

**Runs**: 194 | **COMPLETE**: 28 (14%) | **PARTIAL**: 22 (11%, fast mode — checks skipped) | **INCOMPLETE**: 144 (74%, machine 'not done')
**Mode split**: full 78 / fast 116 (fast = at least one check skipped)

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
| 2026-08-22 | 6 | 1 | 17% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 119 (83% of incomplete)
- `delta`: 64 (44% of incomplete)
- `docs`: 49 (34% of incomplete)
- `lint`: 49 (34% of incomplete)
- `tests`: 27 (19% of incomplete)
- `coverage`: 22 (15% of incomplete)
- `singleton`: 16 (11% of incomplete)
- `audit`: 15 (10% of incomplete)
- `cycle`: 13 (9% of incomplete)
- `complex`: 12 (8% of incomplete)
- `index`: 12 (8% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 175/190 (92%)
- `changelog`: 72/191 (38%)
- `complex`: 178/190 (94%)
- `coverage`: 56/78 (72%)
- `cycle`: 177/190 (93%)
- `delta`: 126/190 (66%)
- `docs`: 144/193 (75%)
- `index`: 178/190 (94%)
- `lint`: 144/193 (75%)
- `singleton`: 174/190 (92%)
- `tests`: 53/80 (66%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.72 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 14.16 / 0.0 / 256.0
- `net_delta`: 27.0 / 2449.92 / -4.0 / 27424.0
- `ruff_errors`: 3.0 / 2.77 / 2.0 / 6.0
- `tests_failed`: 7.0 / 1.73 / 1.0 / 7.0
- `tests_passed`: 4920.0 / 4829.35 / 4583.0 / 5065.0
