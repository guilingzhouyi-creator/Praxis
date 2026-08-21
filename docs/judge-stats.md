## CompletionJudge effectiveness (auto-updated)

**Runs**: 169 | **COMPLETE**: 23 (14%) | **PARTIAL**: 21 (12%, fast mode — checks skipped) | **INCOMPLETE**: 125 (74%, machine 'not done')
**Mode split**: full 61 / fast 108 (fast = at least one check skipped)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 23 | 4 | 17% |
| 2026-08-19 | 22 | 10 | 45% |
| 2026-08-20 | 8 | 4 | 50% |
| 2026-08-21 | 2 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 105 (84% of incomplete)
- `delta`: 56 (45% of incomplete)
- `docs`: 41 (33% of incomplete)
- `lint`: 37 (30% of incomplete)
- `tests`: 19 (15% of incomplete)
- `singleton`: 15 (12% of incomplete)
- `coverage`: 14 (11% of incomplete)
- `complex`: 11 (9% of incomplete)
- `cycle`: 11 (9% of incomplete)
- `index`: 11 (9% of incomplete)
- `audit`: 7 (6% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 158/165 (96%)
- `changelog`: 61/166 (37%)
- `complex`: 154/165 (93%)
- `coverage`: 47/61 (77%)
- `cycle`: 154/165 (93%)
- `delta`: 109/165 (66%)
- `docs`: 127/168 (76%)
- `index`: 154/165 (93%)
- `lint`: 131/168 (78%)
- `singleton`: 150/165 (91%)
- `tests`: 44/63 (70%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 66.07 / 0.0 / 68.0
- `mega_funcs`: 3.0 / 14.33 / 0.0 / 211.0
- `net_delta`: 542.0 / 2683.42 / -4.0 / 27424.0
- `ruff_errors`: 6.0 / 2.78 / 2.0 / 6.0
- `tests_failed`: 2.0 / 1.2 / 1.0 / 2.0
- `tests_passed`: 4925.0 / 4767.19 / 4583.0 / 4925.0
