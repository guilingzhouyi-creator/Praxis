## CompletionJudge effectiveness (auto-updated)

**Runs**: 239 | **COMPLETE**: 34 (14%) | **PARTIAL**: 44 (18%, fast mode — checks skipped) | **INCOMPLETE**: 161 (67%, machine 'not done')
**Mode split**: full 91 / fast 148 (fast = at least one check skipped)

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
| 2026-08-23 | 17 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 136 (84% of incomplete)
- `delta`: 72 (45% of incomplete)
- `lint`: 54 (34% of incomplete)
- `docs`: 52 (32% of incomplete)
- `tests`: 29 (18% of incomplete)
- `coverage`: 25 (16% of incomplete)
- `audit`: 18 (11% of incomplete)
- `singleton`: 16 (10% of incomplete)
- `cycle`: 13 (8% of incomplete)
- `complex`: 12 (7% of incomplete)
- `index`: 12 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 196/214 (92%)
- `changelog`: 79/215 (37%)
- `complex`: 202/214 (94%)
- `coverage`: 66/91 (73%)
- `cycle`: 201/214 (94%)
- `delta`: 142/214 (66%)
- `docs`: 165/217 (76%)
- `index`: 202/214 (94%)
- `lint`: 163/217 (75%)
- `singleton`: 198/214 (93%)
- `tests`: 64/93 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.93 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 12.83 / 0.0 / 256.0
- `net_delta`: 478.0 / 2247.8 / -4.0 / 27424.0
- `ruff_errors`: 2.0 / 2.73 / 2.0 / 6.0
- `tests_failed`: 1.0 / 1.67 / 1.0 / 7.0
- `tests_passed`: 4964.0 / 4847.51 / 4583.0 / 5065.0
