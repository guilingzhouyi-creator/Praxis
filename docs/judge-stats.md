## CompletionJudge effectiveness (auto-updated)

**Runs**: 208 | **COMPLETE**: 32 (15%) | **PARTIAL**: 24 (12%, fast mode — checks skipped) | **INCOMPLETE**: 152 (73%, machine 'not done')
**Mode split**: full 87 / fast 121 (fast = at least one check skipped)

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
| 2026-08-22 | 20 | 5 | 25% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 127 (84% of incomplete)
- `delta`: 68 (45% of incomplete)
- `lint`: 53 (35% of incomplete)
- `docs`: 50 (33% of incomplete)
- `tests`: 28 (18% of incomplete)
- `coverage`: 24 (16% of incomplete)
- `audit`: 18 (12% of incomplete)
- `singleton`: 16 (11% of incomplete)
- `cycle`: 13 (9% of incomplete)
- `complex`: 12 (8% of incomplete)
- `index`: 12 (8% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 185/203 (91%)
- `changelog`: 77/204 (38%)
- `complex`: 191/203 (94%)
- `coverage`: 63/87 (72%)
- `cycle`: 190/203 (94%)
- `delta`: 135/203 (67%)
- `docs`: 156/206 (76%)
- `index`: 191/203 (94%)
- `lint`: 153/206 (74%)
- `singleton`: 187/203 (92%)
- `tests`: 61/89 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.88 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 13.39 / 0.0 / 256.0
- `net_delta`: 18.0 / 2323.86 / -4.0 / 27424.0
- `ruff_errors`: 3.0 / 2.79 / 2.0 / 6.0
- `tests_failed`: 1.0 / 1.7 / 1.0 / 7.0
- `tests_passed`: 4943.0 / 4842.41 / 4583.0 / 5065.0
