## CompletionJudge effectiveness (auto-updated)

**Runs**: 189 | **COMPLETE**: 27 (14%) | **PARTIAL**: 22 (12%, fast mode — checks skipped) | **INCOMPLETE**: 140 (74%, machine 'not done')
**Mode split**: full 74 / fast 115 (fast = at least one check skipped)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 23 | 4 | 17% |
| 2026-08-19 | 22 | 10 | 45% |
| 2026-08-20 | 8 | 4 | 50% |
| 2026-08-21 | 21 | 4 | 19% |
| 2026-08-22 | 1 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 117 (84% of incomplete)
- `delta`: 61 (44% of incomplete)
- `docs`: 49 (35% of incomplete)
- `lint`: 48 (34% of incomplete)
- `tests`: 27 (19% of incomplete)
- `coverage`: 22 (16% of incomplete)
- `singleton`: 16 (11% of incomplete)
- `audit`: 15 (11% of incomplete)
- `cycle`: 13 (9% of incomplete)
- `complex`: 12 (9% of incomplete)
- `index`: 12 (9% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 170/185 (92%)
- `changelog`: 69/186 (37%)
- `complex`: 173/185 (94%)
- `coverage`: 52/74 (70%)
- `cycle`: 172/185 (93%)
- `delta`: 124/185 (67%)
- `docs`: 139/188 (74%)
- `index`: 173/185 (94%)
- `lint`: 140/188 (74%)
- `singleton`: 169/185 (91%)
- `tests`: 49/76 (64%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 69.0 / 66.6 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 14.48 / 0.0 / 256.0
- `net_delta`: 130.0 / 2533.68 / -4.0 / 27424.0
- `ruff_errors`: 3.0 / 2.75 / 2.0 / 6.0
- `tests_failed`: 7.0 / 1.73 / 1.0 / 7.0
- `tests_passed`: 5065.0 / 4817.96 / 4583.0 / 5065.0
