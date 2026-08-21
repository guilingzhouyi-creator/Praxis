## CompletionJudge effectiveness (auto-updated)

**Runs**: 183 | **COMPLETE**: 25 (14%) | **PARTIAL**: 21 (11%, fast mode — checks skipped) | **INCOMPLETE**: 137 (75%, machine 'not done')
**Mode split**: full 71 / fast 112 (fast = at least one check skipped)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 23 | 4 | 17% |
| 2026-08-19 | 22 | 10 | 45% |
| 2026-08-20 | 8 | 4 | 50% |
| 2026-08-21 | 16 | 2 | 12% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 114 (83% of incomplete)
- `delta`: 60 (44% of incomplete)
- `docs`: 48 (35% of incomplete)
- `lint`: 46 (34% of incomplete)
- `tests`: 26 (19% of incomplete)
- `coverage`: 21 (15% of incomplete)
- `singleton`: 16 (12% of incomplete)
- `cycle`: 13 (9% of incomplete)
- `audit`: 13 (9% of incomplete)
- `complex`: 12 (9% of incomplete)
- `index`: 12 (9% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 166/179 (93%)
- `changelog`: 66/180 (37%)
- `complex`: 167/179 (93%)
- `coverage`: 50/71 (70%)
- `cycle`: 166/179 (93%)
- `delta`: 119/179 (66%)
- `docs`: 134/182 (74%)
- `index`: 167/179 (93%)
- `lint`: 136/182 (75%)
- `singleton`: 163/179 (91%)
- `tests`: 47/73 (64%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 69.0 / 66.48 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 14.9 / 0.0 / 256.0
- `net_delta`: 8.0 / 2565.19 / -4.0 / 27424.0
- `ruff_errors`: 2.0 / 2.7 / 2.0 / 6.0
- `tests_failed`: 2.0 / 1.48 / 1.0 / 3.0
- `tests_passed`: 5065.0 / 4807.0 / 4583.0 / 5065.0
