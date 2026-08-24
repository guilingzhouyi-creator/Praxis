## CompletionJudge effectiveness (auto-updated)

**Runs**: 220 | **COMPLETE**: 34 (15%) | **PARTIAL**: 22 (10%, fast mode — checks skipped) | **INCOMPLETE**: 164 (75%, machine 'not done')
**Mode split**: full 91 / fast 129 (fast = at least one check skipped)

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
| 2026-08-24 | 3 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 139 (85% of incomplete)
- `delta`: 73 (45% of incomplete)
- `lint`: 57 (35% of incomplete)
- `docs`: 52 (32% of incomplete)
- `tests`: 29 (18% of incomplete)
- `coverage`: 25 (15% of incomplete)
- `audit`: 20 (12% of incomplete)
- `singleton`: 16 (10% of incomplete)
- `cycle`: 13 (8% of incomplete)
- `complex`: 12 (7% of incomplete)
- `index`: 12 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 197/217 (91%)
- `changelog`: 79/218 (36%)
- `complex`: 205/217 (94%)
- `coverage`: 66/91 (73%)
- `cycle`: 204/217 (94%)
- `delta`: 144/217 (66%)
- `docs`: 168/220 (76%)
- `index`: 205/217 (94%)
- `lint`: 163/220 (74%)
- `singleton`: 201/217 (93%)
- `tests`: 64/93 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.93 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 12.68 / 0.0 / 256.0
- `net_delta`: 2.0 / 2233.07 / -4.0 / 27424.0
- `ruff_errors`: 2.0 / 2.61 / 2.0 / 6.0
- `tests_failed`: 1.0 / 1.67 / 1.0 / 7.0
- `tests_passed`: 4964.0 / 4847.51 / 4583.0 / 5065.0
