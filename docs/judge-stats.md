## CompletionJudge effectiveness (auto-updated)

**Runs**: 233 | **COMPLETE**: 34 (15%) | **PARTIAL**: 24 (10%, fast mode — checks skipped) | **INCOMPLETE**: 175 (75%, machine 'not done')
**Mode split**: full 91 (37% complete) / fast 142 (fast = at least one check skipped)
**Skipped tests notice**: tests skipped in 24 judge run(s) (full mode / WSL slice-serial required before merge)
**Gate exemptions** (MERGE_GATE_SKIP commits in history): 11
**Waived delta passes**: 3 judge run(s) passed net-delta via MERGE_GATE_SKIP (not a qualifying delta)

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
| 2026-08-25 | 12 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 150 (86% of incomplete)
- `delta`: 75 (43% of incomplete)
- `lint`: 60 (34% of incomplete)
- `docs`: 53 (30% of incomplete)
- `tests`: 29 (17% of incomplete)
- `coverage`: 25 (14% of incomplete)
- `audit`: 23 (13% of incomplete)
- `singleton`: 17 (10% of incomplete)
- `cycle`: 14 (8% of incomplete)
- `complex`: 13 (7% of incomplete)
- `index`: 13 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 206/229 (90%)
- `changelog`: 81/231 (35%)
- `complex`: 217/230 (94%)
- `coverage`: 67/92 (73%)
- `cycle`: 216/230 (94%)
- `delta`: 155/230 (67%)
- `docs`: 180/233 (77%)
- `index`: 217/230 (94%)
- `lint`: 173/233 (74%)
- `singleton`: 213/230 (93%)
- `tests`: 64/93 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.93 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 13.54 / 0.0 / 316.0
- `net_delta`: 499.0 / 2165.49 / -4.0 / 27424.0
- `ruff_errors`: 0.0 / 1.68 / 0.0 / 6.0
- `tests_failed`: 1.0 / 1.67 / 1.0 / 7.0
- `tests_passed`: 4964.0 / 4847.51 / 4583.0 / 5065.0
