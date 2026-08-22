## CompletionJudge effectiveness (auto-updated)

**Runs**: 154 | **COMPLETE**: 17 (11%) | **PARTIAL**: 20 (13%, fast mode — checks skipped) | **INCOMPLETE**: 117 (76%, machine 'not done')
**Mode split**: full 50 / fast 104 (fast = at least one check skipped)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 23 | 4 | 17% |
| 2026-08-19 | 17 | 8 | 47% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 100 (85% of incomplete)
- `delta`: 53 (45% of incomplete)
- `docs`: 36 (31% of incomplete)
- `lint`: 33 (28% of incomplete)
- `tests`: 16 (14% of incomplete)
- `singleton`: 15 (13% of incomplete)
- `coverage`: 12 (10% of incomplete)
- `complex`: 11 (9% of incomplete)
- `cycle`: 11 (9% of incomplete)
- `index`: 11 (9% of incomplete)
- `audit`: 5 (4% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 145/150 (97%)
- `changelog`: 51/151 (34%)
- `complex`: 139/150 (93%)
- `coverage`: 38/50 (76%)
- `cycle`: 139/150 (93%)
- `delta`: 97/150 (65%)
- `docs`: 117/153 (76%)
- `index`: 139/150 (93%)
- `lint`: 120/153 (78%)
- `singleton`: 135/150 (90%)
- `tests`: 36/52 (69%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 65.59 / 0.0 / 68.0
- `mega_funcs`: 3.0 / 15.61 / 0.0 / 211.0
- `net_delta`: 0.0 / 335.92 / -4.0 / 3828.0
- `ruff_errors`: 2.0 / 2.0 / 2.0 / 2.0
- `tests_failed`: 1.0 / 1.08 / 1.0 / 2.0
- `tests_passed`: 4828.0 / 4739.23 / 4583.0 / 4828.0
