## CompletionJudge effectiveness (auto-updated)

**Runs**: 179 | **COMPLETE**: 23 (13%) | **PARTIAL**: 21 (12%, fast mode — checks skipped) | **INCOMPLETE**: 135 (75%, machine 'not done')
**Mode split**: full 68 / fast 111 (fast = at least one check skipped)

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 23 | 4 | 17% |
| 2026-08-19 | 22 | 10 | 45% |
| 2026-08-20 | 8 | 4 | 50% |
| 2026-08-21 | 12 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 113 (84% of incomplete)
- `delta`: 59 (44% of incomplete)
- `docs`: 46 (34% of incomplete)
- `lint`: 45 (33% of incomplete)
- `tests`: 26 (19% of incomplete)
- `coverage`: 21 (16% of incomplete)
- `singleton`: 16 (12% of incomplete)
- `cycle`: 13 (10% of incomplete)
- `complex`: 12 (9% of incomplete)
- `index`: 12 (9% of incomplete)
- `audit`: 12 (9% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 163/175 (93%)
- `changelog`: 63/176 (36%)
- `complex`: 163/175 (93%)
- `coverage`: 47/68 (69%)
- `cycle`: 162/175 (93%)
- `delta`: 116/175 (66%)
- `docs`: 132/178 (74%)
- `index`: 163/175 (93%)
- `lint`: 133/178 (75%)
- `singleton`: 159/175 (91%)
- `tests`: 44/70 (63%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 69.0 / 66.36 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 15.19 / 0.0 / 256.0
- `net_delta`: -3.0 / 2595.63 / -4.0 / 27424.0
- `ruff_errors`: 2.0 / 2.7 / 2.0 / 6.0
- `tests_failed`: 2.0 / 1.48 / 1.0 / 3.0
- `tests_passed`: 5063.0 / 4794.91 / 4583.0 / 5063.0
