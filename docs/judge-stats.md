## CompletionJudge effectiveness (auto-updated)

**Runs**: 245 | **COMPLETE**: 37 (15%) | **PARTIAL**: 28 (11%, fast mode — checks skipped) | **INCOMPLETE**: 180 (73%, machine 'not done')
**Mode split**: full 99 (37% complete) / fast 146 (fast = at least one check skipped)
**Skipped tests notice**: tests skipped in 28 judge run(s) (full mode / WSL slice-serial required before merge)
**Gate exemptions** (MERGE_GATE_SKIP commits in history): 11
**Waived delta passes**: 4 judge run(s) passed net-delta via MERGE_GATE_SKIP (not a qualifying delta)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 22 | 4 | 18% |
| 2026-08-19 | 22 | 10 | 45% |
| 2026-08-20 | 8 | 4 | 50% |
| 2026-08-21 | 21 | 4 | 19% |
| 2026-08-22 | 25 | 7 | 28% |
| 2026-08-23 | 5 | 0 | 0% |
| 2026-08-24 | 4 | 0 | 0% |
| 2026-08-25 | 19 | 1 | 5% |
| 2026-08-26 | 5 | 2 | 40% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 154 (86% of incomplete)
- `delta`: 75 (42% of incomplete)
- `lint`: 60 (33% of incomplete)
- `docs`: 54 (30% of incomplete)
- `tests`: 32 (18% of incomplete)
- `coverage`: 28 (16% of incomplete)
- `audit`: 24 (13% of incomplete)
- `singleton`: 17 (9% of incomplete)
- `cycle`: 14 (8% of incomplete)
- `complex`: 13 (7% of incomplete)
- `index`: 13 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 217/241 (90%)
- `changelog`: 89/243 (37%)
- `complex`: 229/242 (95%)
- `coverage`: 72/100 (72%)
- `cycle`: 228/242 (94%)
- `delta`: 167/242 (69%)
- `docs`: 191/245 (78%)
- `index`: 229/242 (95%)
- `lint`: 185/245 (76%)
- `singleton`: 225/242 (93%)
- `tests`: 69/101 (68%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 67.02 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 12.99 / 0.0 / 316.0
- `net_delta`: 499.0 / 2165.49 / -4.0 / 27424.0
- `ruff_errors`: 0.0 / 1.21 / 0.0 / 6.0
- `tests_failed`: 0.0 / 1.34 / 0.0 / 7.0
- `tests_passed`: 5046.0 / 4809.87 / 2302.0 / 5065.0
