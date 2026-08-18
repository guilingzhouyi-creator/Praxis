## CompletionJudge effectiveness (auto-updated)

**Runs**: 117 | **COMPLETE**: 5 (4%) | **PARTIAL**: 17 (15%, fast mode — checks skipped) | **INCOMPLETE**: 95 (81%, machine 'not done')
**Mode split**: full 26 / fast 91 (fast = at least one check skipped)
**Duration** (full runs): avg 464s / P95 897s (26 runs) — fast runs: avg 22s / P95 118s (91 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 3 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 81 (85% of incomplete)
- `delta`: 49 (52% of incomplete)
- `docs`: 33 (35% of incomplete)
- `lint`: 32 (34% of incomplete)
- `singleton`: 15 (16% of incomplete)
- `tests`: 14 (15% of incomplete)
- `complex`: 11 (12% of incomplete)
- `cycle`: 11 (12% of incomplete)
- `index`: 11 (12% of incomplete)
- `coverage`: 10 (11% of incomplete)
- `audit`: 5 (5% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 3/83 (4%)
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
- `feature/ci-bench-smoke`: 0/1 (0%)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 109/114 (96%)
- `changelog`: 34/115 (30%)
- `complex`: 103/114 (90%)
- `coverage`: 16/26 (62%)
- `cycle`: 103/114 (90%)
- `delta`: 65/114 (57%)
- `docs`: 84/117 (72%)
- `index`: 103/114 (90%)
- `lint`: 85/117 (73%)
- `singleton`: 99/114 (87%)
- `tests`: 14/28 (50%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 44
- `changelog + docs`: 27
- `changelog + lint`: 27
- `docs + lint`: 18
- `delta + lint`: 17

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 67.0 / 63.33 / 0.0 / 67.0
- `mega_funcs`: 2.0 / 20.46 / 0.0 / 211.0
- `net_delta`: -4.0 / 332.81 / -4.0 / 3828.0
- `ruff_errors`: 2.0 / 2.0 / 2.0 / 2.0
- `tests_failed`: 1.0 / 1.1 / 1.0 / 2.0
- `tests_passed`: 4767.0 / 4669.57 / 4583.0 / 4767.0
