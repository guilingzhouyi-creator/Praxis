## CompletionJudge effectiveness (auto-updated)

**Runs**: 105 | **COMPLETE**: 5 (5%) | **PARTIAL**: 17 (16%, fast mode — checks skipped) | **INCOMPLETE**: 83 (79%, machine 'not done')
**Mode split**: full 20 / fast 85 (fast = at least one check skipped)
**Duration** (full runs): avg 400s / P95 740s (20 runs) — fast runs: avg 18s / P95 99s (85 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 36 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 70 (84% of incomplete)
- `delta`: 43 (52% of incomplete)
- `docs`: 24 (29% of incomplete)
- `lint`: 23 (28% of incomplete)
- `singleton`: 14 (17% of incomplete)
- `tests`: 11 (13% of incomplete)
- `complex`: 10 (12% of incomplete)
- `cycle`: 10 (12% of incomplete)
- `index`: 10 (12% of incomplete)
- `coverage`: 7 (8% of incomplete)
- `audit`: 5 (6% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 3/72 (4%)
- `feature/test-matrix-prebuild`: 0/7 (0%)
- `feature/perf-hotpath`: 1/4 (25%)
- `feature/judge-verdict-mode`: 1/4 (25%)
- `feature/test-runner-slicing`: 0/4 (0%)
- `feature/l3a-fidelity`: 0/4 (0%)
- `fix/runner-hang`: 0/2 (0%)
- `feature/test-opt`: 0/2 (0%)
- `feature/test-opt-sweep`: 0/2 (0%)
- `feature/identity-uid`: 0/2 (0%)
- `feature/root-security-toolchain`: 0/2 (0%)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 97/102 (95%)
- `changelog`: 33/103 (32%)
- `complex`: 92/102 (90%)
- `coverage`: 13/20 (65%)
- `cycle`: 92/102 (90%)
- `delta`: 59/102 (58%)
- `docs`: 81/105 (77%)
- `index`: 92/102 (90%)
- `lint`: 82/105 (78%)
- `singleton`: 88/102 (86%)
- `tests`: 11/22 (50%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 39
- `changelog + docs`: 19
- `changelog + lint`: 18
- `changelog + singleton`: 14
- `delta + lint`: 13

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 67.0 / 66.38 / 66.0 / 67.0
- `mega_funcs`: 2.0 / 20.6 / 0.0 / 211.0
- `net_delta`: -1.0 / 374.04 / -2.0 / 3828.0
- `tests_failed`: 1.0 / 1.12 / 1.0 / 2.0
- `tests_passed`: 4766.0 / 4642.61 / 4583.0 / 4766.0
