## CompletionJudge effectiveness (auto-updated)

**Runs**: 221 | **COMPLETE**: 34 (15%) | **PARTIAL**: 22 (10%, fast mode — checks skipped) | **INCOMPLETE**: 165 (75%, machine 'not done')
**Mode split**: full 91 (37% complete) / fast 130 (fast = at least one check skipped)
**Skipped tests notice**: tests skipped in 12 judge run(s) (full mode / WSL slice-serial required before merge)
**Gate exemptions** (MERGE_GATE_SKIP commits in history): 7

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

**Failures by check** (most frequent evidence gaps):
- `changelog`: 140 (85% of incomplete)
- `delta`: 74 (45% of incomplete)
- `lint`: 58 (35% of incomplete)
- `docs`: 52 (32% of incomplete)
- `tests`: 29 (18% of incomplete)
- `coverage`: 25 (15% of incomplete)
- `audit`: 21 (13% of incomplete)
- `singleton`: 16 (10% of incomplete)
- `cycle`: 13 (8% of incomplete)
- `complex`: 12 (7% of incomplete)
- `index`: 12 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 197/218 (90%)
- `changelog`: 79/219 (36%)
- `complex`: 206/218 (94%)
- `coverage`: 66/91 (73%)
- `cycle`: 205/218 (94%)
- `delta`: 144/218 (66%)
- `docs`: 169/221 (76%)
- `index`: 206/218 (94%)
- `lint`: 163/221 (74%)
- `singleton`: 202/218 (93%)
- `tests`: 64/93 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.93 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 12.63 / 0.0 / 256.0
- `net_delta`: 2.0 / 2212.21 / -4.0 / 27424.0
- `ruff_errors`: 2.0 / 2.58 / 2.0 / 6.0
- `tests_failed`: 1.0 / 1.67 / 1.0 / 7.0
- `tests_passed`: 4964.0 / 4847.51 / 4583.0 / 5065.0
