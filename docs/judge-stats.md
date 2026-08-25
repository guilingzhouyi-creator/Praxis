## CompletionJudge effectiveness (auto-updated)

**Runs**: 226 | **COMPLETE**: 34 (15%) | **PARTIAL**: 23 (10%, fast mode — checks skipped) | **INCOMPLETE**: 169 (75%, machine 'not done')
**Mode split**: full 91 (37% complete) / fast 135 (fast = at least one check skipped)
**Skipped tests notice**: tests skipped in 17 judge run(s) (full mode / WSL slice-serial required before merge)
**Gate exemptions** (MERGE_GATE_SKIP commits in history): 11
**Waived delta passes**: 1 judge run(s) passed net-delta via MERGE_GATE_SKIP (not a qualifying delta)

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
| 2026-08-25 | 5 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 144 (85% of incomplete)
- `delta`: 75 (44% of incomplete)
- `lint`: 59 (35% of incomplete)
- `docs`: 52 (31% of incomplete)
- `tests`: 29 (17% of incomplete)
- `coverage`: 25 (15% of incomplete)
- `audit`: 22 (13% of incomplete)
- `singleton`: 16 (9% of incomplete)
- `cycle`: 13 (8% of incomplete)
- `complex`: 12 (7% of incomplete)
- `index`: 12 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 200/222 (90%)
- `changelog`: 80/224 (36%)
- `complex`: 211/223 (95%)
- `coverage`: 67/92 (73%)
- `cycle`: 210/223 (94%)
- `delta`: 148/223 (66%)
- `docs`: 174/226 (77%)
- `index`: 211/223 (95%)
- `lint`: 167/226 (74%)
- `singleton`: 207/223 (93%)
- `tests`: 64/93 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.93 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 12.4 / 0.0 / 256.0
- `net_delta`: 499.0 / 2180.78 / -4.0 / 27424.0
- `ruff_errors`: 0.0 / 2.12 / 0.0 / 6.0
- `tests_failed`: 1.0 / 1.67 / 1.0 / 7.0
- `tests_passed`: 4964.0 / 4847.51 / 4583.0 / 5065.0
