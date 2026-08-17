## CompletionJudge effectiveness (auto-updated)

**Runs**: 97 | **COMPLETE**: 5 (5%) | **PARTIAL**: 17 (18%, fast mode — checks skipped) | **INCOMPLETE**: 75 (77%, machine 'not done')
**Mode split**: full 15 / fast 82 (fast = at least one check skipped)
**Duration** (full runs): avg 357s / P95 636s (15 runs) — fast runs: avg 14s / P95 80s (82 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 28 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 63 (84% of incomplete)
- `delta`: 37 (49% of incomplete)
- `docs`: 22 (29% of incomplete)
- `lint`: 22 (29% of incomplete)
- `singleton`: 13 (17% of incomplete)
- `complex`: 9 (12% of incomplete)
- `cycle`: 9 (12% of incomplete)
- `index`: 9 (12% of incomplete)
- `tests`: 6 (8% of incomplete)
- `audit`: 5 (7% of incomplete)
- `coverage`: 4 (5% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 3/64 (5%)
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
- `audit`: 89/94 (95%)
- `changelog`: 32/95 (34%)
- `complex`: 85/94 (90%)
- `coverage`: 11/15 (73%)
- `cycle`: 85/94 (90%)
- `delta`: 57/94 (61%)
- `docs`: 75/97 (77%)
- `index`: 85/94 (90%)
- `lint`: 75/97 (77%)
- `singleton`: 81/94 (86%)
- `tests`: 11/17 (65%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 33
- `changelog + docs`: 17
- `changelog + lint`: 17
- `changelog + singleton`: 13
- `delta + lint`: 13

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 67.0 / 66.17 / 66.0 / 67.0
- `mega_funcs`: 2.0 / 19.85 / 0.0 / 211.0
- `net_delta`: 0.0 / 423.78 / -2.0 / 3828.0
- `tests_failed`: 1.0 / 1.0 / 1.0 / 1.0
- `tests_passed`: 4687.0 / 4607.43 / 4583.0 / 4687.0
