## CompletionJudge effectiveness (auto-updated)

**Runs**: 140 | **COMPLETE**: 9 (6%) | **PARTIAL**: 20 (14%, fast mode — checks skipped) | **INCOMPLETE**: 111 (79%, machine 'not done')
**Mode split**: full 37 / fast 103 (fast = at least one check skipped)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 23 | 4 | 17% |
| 2026-08-19 | 3 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 96 (86% of incomplete)
- `delta`: 53 (48% of incomplete)
- `docs`: 36 (32% of incomplete)
- `lint`: 32 (29% of incomplete)
- `singleton`: 15 (14% of incomplete)
- `tests`: 15 (14% of incomplete)
- `coverage`: 12 (11% of incomplete)
- `complex`: 11 (10% of incomplete)
- `cycle`: 11 (10% of incomplete)
- `index`: 11 (10% of incomplete)
- `audit`: 5 (5% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 131/136 (96%)
- `changelog`: 41/137 (30%)
- `complex`: 125/136 (92%)
- `coverage`: 25/37 (68%)
- `cycle`: 125/136 (92%)
- `delta`: 83/136 (61%)
- `docs`: 103/139 (74%)
- `index`: 125/136 (92%)
- `lint`: 107/139 (77%)
- `singleton`: 121/136 (89%)
- `tests`: 24/39 (62%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 67.0 / 64.58 / 0.0 / 68.0
- `mega_funcs`: 2.0 / 17.15 / 0.0 / 211.0
- `net_delta`: 986.0 / 340.71 / -4.0 / 3828.0
- `ruff_errors`: 2.0 / 2.0 / 2.0 / 2.0
- `tests_failed`: 1.0 / 1.09 / 1.0 / 2.0
- `tests_passed`: 4799.0 / 4708.85 / 4583.0 / 4809.0
