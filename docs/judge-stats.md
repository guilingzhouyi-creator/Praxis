## CompletionJudge effectiveness (auto-updated)

**Runs**: 101 | **COMPLETE**: 5 (5%) | **PARTIAL**: 17 (17%, fast mode — checks skipped) | **INCOMPLETE**: 79 (78%, machine 'not done')
**Mode split**: full 18 / fast 83 (fast = at least one check skipped)
**Duration** (full runs): avg 367s / P95 636s (18 runs) — fast runs: avg 15s / P95 90s (83 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 32 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 66 (84% of incomplete)
- `delta`: 39 (49% of incomplete)
- `docs`: 24 (30% of incomplete)
- `lint`: 23 (29% of incomplete)
- `singleton`: 14 (18% of incomplete)
- `complex`: 10 (13% of incomplete)
- `cycle`: 10 (13% of incomplete)
- `index`: 10 (13% of incomplete)
- `tests`: 9 (11% of incomplete)
- `coverage`: 6 (8% of incomplete)
- `audit`: 5 (6% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 3/68 (4%)
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
- `audit`: 93/98 (95%)
- `changelog`: 33/99 (33%)
- `complex`: 88/98 (90%)
- `coverage`: 12/18 (67%)
- `cycle`: 88/98 (90%)
- `delta`: 59/98 (60%)
- `docs`: 77/101 (76%)
- `index`: 88/98 (90%)
- `lint`: 78/101 (77%)
- `singleton`: 84/98 (86%)
- `tests`: 11/20 (55%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 35
- `changelog + docs`: 19
- `changelog + lint`: 18
- `changelog + singleton`: 14
- `delta + lint`: 13

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 67.0 / 66.29 / 66.0 / 67.0
- `mega_funcs`: 2.0 / 21.47 / 0.0 / 211.0
- `net_delta`: 3.0 / 405.87 / -2.0 / 3828.0
- `tests_failed`: 1.0 / 1.17 / 1.0 / 2.0
- `tests_passed`: 4766.0 / 4627.19 / 4583.0 / 4766.0
