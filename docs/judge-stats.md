## CompletionJudge effectiveness (auto-updated)

**Runs**: 56 | **COMPLETE**: 4 (7%) | **PARTIAL**: 8 (14%, fast mode — checks skipped) | **INCOMPLETE**: 44 (79%, machine 'not done')
**Mode split**: full 11 / fast 45 (fast = at least one check skipped)
**Duration** (full runs): avg 383s / P95 636s (11 runs) — fast runs: avg 9s / P95 15s (45 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 25 | 4 | 16% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 41 (93% of incomplete)
- `delta`: 27 (61% of incomplete)
- `lint`: 10 (23% of incomplete)
- `singleton`: 9 (20% of incomplete)
- `docs`: 8 (18% of incomplete)
- `complex`: 5 (11% of incomplete)
- `cycle`: 5 (11% of incomplete)
- `index`: 5 (11% of incomplete)
- `tests`: 2 (5% of incomplete)
- `audit`: 1 (2% of incomplete)
- `coverage`: 1 (2% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 2/44 (5%)
- `feature/perf-hotpath`: 1/4 (25%)
- `feature/judge-verdict-mode`: 1/4 (25%)
- `feature/test-runner-slicing`: 0/4 (0%)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 54/55 (98%)
- `changelog`: 14/55 (25%)
- `complex`: 50/55 (91%)
- `coverage`: 10/11 (91%)
- `cycle`: 50/55 (91%)
- `delta`: 29/56 (52%)
- `docs`: 48/56 (86%)
- `index`: 50/55 (91%)
- `lint`: 46/56 (82%)
- `singleton`: 46/55 (84%)
- `tests`: 9/11 (82%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 26
- `changelog + lint`: 10
- `changelog + singleton`: 9
- `lint + singleton`: 7
- `changelog + docs`: 6

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 66.0 / 66.0 / 66.0 / 66.0
- `mega_funcs`: 205.0 / 17.5 / 0.0 / 205.0
- `net_delta`: 36.0 / 347.88 / -2.0 / 3828.0
- `tests_failed`: 1.0 / 1.0 / 1.0 / 1.0
- `tests_passed`: 4600.0 / 4594.1 / 4583.0 / 4600.0
