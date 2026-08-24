## CompletionJudge effectiveness (auto-updated)

**Runs**: 252 | **COMPLETE**: 34 (13%) | **PARTIAL**: 56 (22%, fast mode — checks skipped) | **INCOMPLETE**: 162 (64%, machine 'not done')
**Mode split**: full 91 / fast 161 (fast = at least one check skipped)

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
| 2026-08-23 | 29 | 0 | 0% |
| 2026-08-24 | 1 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 137 (85% of incomplete)
- `delta`: 72 (44% of incomplete)
- `lint`: 55 (34% of incomplete)
- `docs`: 52 (32% of incomplete)
- `tests`: 29 (18% of incomplete)
- `coverage`: 25 (15% of incomplete)
- `audit`: 18 (11% of incomplete)
- `singleton`: 16 (10% of incomplete)
- `cycle`: 13 (8% of incomplete)
- `complex`: 12 (7% of incomplete)
- `index`: 12 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 197/215 (92%)
- `changelog`: 79/216 (37%)
- `complex`: 203/215 (94%)
- `coverage`: 66/91 (73%)
- `cycle`: 202/215 (94%)
- `delta`: 143/215 (67%)
- `docs`: 166/218 (76%)
- `index`: 203/215 (94%)
- `lint`: 163/218 (75%)
- `singleton`: 199/215 (93%)
- `tests`: 64/93 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.93 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 12.78 / 0.0 / 256.0
- `net_delta`: 4139.0 / 2265.98 / -4.0 / 27424.0
- `ruff_errors`: 2.0 / 2.69 / 2.0 / 6.0
- `tests_failed`: 1.0 / 1.67 / 1.0 / 7.0
- `tests_passed`: 4964.0 / 4847.51 / 4583.0 / 5065.0
