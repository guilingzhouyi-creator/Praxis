## CompletionJudge effectiveness (auto-updated)

**Runs**: 107 | **COMPLETE**: 5 (5%) | **PARTIAL**: 17 (16%, fast mode — checks skipped) | **INCOMPLETE**: 85 (79%, machine 'not done')
**Mode split**: full 21 / fast 86 (fast = at least one check skipped)
**Duration** (full runs): avg 415s / P95 721s (21 runs) — fast runs: avg 19s / P95 118s (86 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 38 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 72 (85% of incomplete)
- `delta`: 45 (53% of incomplete)
- `docs`: 26 (31% of incomplete)
- `lint`: 25 (29% of incomplete)
- `singleton`: 14 (16% of incomplete)
- `tests`: 12 (14% of incomplete)
- `complex`: 10 (12% of incomplete)
- `cycle`: 10 (12% of incomplete)
- `index`: 10 (12% of incomplete)
- `coverage`: 8 (9% of incomplete)
- `audit`: 5 (6% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 3/74 (4%)
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
- `audit`: 99/104 (95%)
- `changelog`: 33/105 (31%)
- `complex`: 94/104 (90%)
- `coverage`: 13/21 (62%)
- `cycle`: 94/104 (90%)
- `delta`: 59/104 (57%)
- `docs`: 81/107 (76%)
- `index`: 94/104 (90%)
- `lint`: 82/107 (77%)
- `singleton`: 90/104 (87%)
- `tests`: 11/23 (48%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 41
- `changelog + docs`: 21
- `changelog + lint`: 20
- `delta + lint`: 15
- `changelog + singleton`: 14

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 0.0 / 62.47 / 0.0 / 67.0
- `mega_funcs`: 2.0 / 20.19 / 0.0 / 211.0
- `net_delta`: 43.0 / 361.55 / -2.0 / 3828.0
- `ruff_errors`: 2.0 / 2.0 / 2.0 / 2.0
- `tests_failed`: 1.0 / 1.11 / 1.0 / 2.0
- `tests_passed`: 4766.0 / 4649.11 / 4583.0 / 4766.0
