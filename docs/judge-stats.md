## CompletionJudge effectiveness (auto-updated)

**Runs**: 172 | **COMPLETE**: 23 (13%) | **PARTIAL**: 21 (12%, fast mode — checks skipped) | **INCOMPLETE**: 128 (74%, machine 'not done')
**Mode split**: full 62 / fast 110 (fast = at least one check skipped)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 23 | 4 | 17% |
| 2026-08-19 | 22 | 10 | 45% |
| 2026-08-20 | 8 | 4 | 50% |
| 2026-08-21 | 5 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 108 (84% of incomplete)
- `delta`: 58 (45% of incomplete)
- `docs`: 44 (34% of incomplete)
- `lint`: 40 (31% of incomplete)
- `tests`: 20 (16% of incomplete)
- `singleton`: 16 (12% of incomplete)
- `coverage`: 15 (12% of incomplete)
- `complex`: 12 (9% of incomplete)
- `cycle`: 12 (9% of incomplete)
- `index`: 12 (9% of incomplete)
- `audit`: 10 (8% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 158/168 (94%)
- `changelog`: 61/169 (36%)
- `complex`: 156/168 (93%)
- `coverage`: 47/62 (76%)
- `cycle`: 156/168 (93%)
- `delta`: 110/168 (65%)
- `docs`: 127/171 (74%)
- `index`: 156/168 (93%)
- `lint`: 131/171 (77%)
- `singleton`: 152/168 (90%)
- `tests`: 44/64 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.07 / 0.0 / 68.0
- `mega_funcs`: 3.0 / 15.74 / 0.0 / 256.0
- `net_delta`: 640.0 / 2626.94 / -4.0 / 27424.0
- `ruff_errors`: 6.0 / 2.78 / 2.0 / 6.0
- `tests_failed`: 2.0 / 1.2 / 1.0 / 2.0
- `tests_passed`: 4925.0 / 4767.19 / 4583.0 / 4925.0
