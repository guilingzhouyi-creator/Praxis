## CompletionJudge effectiveness (auto-updated)

**Runs**: 86 | **COMPLETE**: 5 (6%) | **PARTIAL**: 14 (16%, fast mode — checks skipped) | **INCOMPLETE**: 67 (78%, machine 'not done')
**Mode split**: full 13 / fast 73 (fast = at least one check skipped)
**Duration** (full runs): avg 373s / P95 636s (13 runs) — fast runs: avg 13s / P95 21s (73 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 17 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 59 (88% of incomplete)
- `delta`: 37 (55% of incomplete)
- `lint`: 19 (28% of incomplete)
- `docs`: 18 (27% of incomplete)
- `singleton`: 13 (19% of incomplete)
- `complex`: 9 (13% of incomplete)
- `cycle`: 9 (13% of incomplete)
- `index`: 9 (13% of incomplete)
- `tests`: 5 (7% of incomplete)
- `audit`: 4 (6% of incomplete)
- `coverage`: 2 (3% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 3/57 (5%)
- `feature/test-matrix-prebuild`: 0/7 (0%)
- `feature/perf-hotpath`: 1/4 (25%)
- `feature/judge-verdict-mode`: 1/4 (25%)
- `feature/test-runner-slicing`: 0/4 (0%)
- `feature/l3a-fidelity`: 0/4 (0%)
- `fix/runner-hang`: 0/2 (0%)
- `feature/test-opt`: 0/2 (0%)
- `feature/test-opt-sweep`: 0/2 (0%)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 79/83 (95%)
- `changelog`: 25/84 (30%)
- `complex`: 74/83 (89%)
- `coverage`: 11/13 (85%)
- `cycle`: 74/83 (89%)
- `delta`: 46/83 (55%)
- `docs`: 68/86 (79%)
- `index`: 74/83 (89%)
- `lint`: 67/86 (78%)
- `singleton`: 70/83 (84%)
- `tests`: 10/15 (67%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 33
- `changelog + lint`: 16
- `changelog + docs`: 15
- `changelog + singleton`: 13
- `delta + lint`: 13

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 67.0 / 66.09 / 66.0 / 67.0
- `mega_funcs`: 1.0 / 22.73 / 0.0 / 211.0
- `net_delta`: 369.0 / 321.95 / -2.0 / 3828.0
- `tests_failed`: 1.0 / 1.0 / 1.0 / 1.0
- `tests_passed`: 4626.0 / 4601.31 / 4583.0 / 4626.0
