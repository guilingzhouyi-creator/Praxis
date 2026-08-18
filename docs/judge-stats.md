## CompletionJudge effectiveness (auto-updated)

**Runs**: 121 | **COMPLETE**: 6 (5%) | **PARTIAL**: 17 (14%, fast mode — checks skipped) | **INCOMPLETE**: 98 (81%, machine 'not done')
**Mode split**: full 29 / fast 92 (fast = at least one check skipped)
**Duration** (full runs): avg 501s / P95 1015s (29 runs) — fast runs: avg 23s / P95 118s (92 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 7 | 1 | 14% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 83 (85% of incomplete)
- `delta`: 49 (50% of incomplete)
- `docs`: 34 (35% of incomplete)
- `lint`: 32 (33% of incomplete)
- `singleton`: 15 (15% of incomplete)
- `tests`: 14 (14% of incomplete)
- `complex`: 11 (11% of incomplete)
- `cycle`: 11 (11% of incomplete)
- `index`: 11 (11% of incomplete)
- `coverage`: 10 (10% of incomplete)
- `audit`: 5 (5% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 4/87 (5%)
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
- `audit`: 113/118 (96%)
- `changelog`: 36/119 (30%)
- `complex`: 107/118 (91%)
- `coverage`: 19/29 (66%)
- `cycle`: 107/118 (91%)
- `delta`: 69/118 (58%)
- `docs`: 87/121 (72%)
- `index`: 107/118 (91%)
- `lint`: 89/121 (74%)
- `singleton`: 103/118 (87%)
- `tests`: 17/31 (55%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 44
- `changelog + docs`: 27
- `changelog + lint`: 27
- `docs + lint`: 18
- `delta + lint`: 17

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 67.0 / 63.79 / 0.0 / 67.0
- `mega_funcs`: 2.0 / 19.75 / 0.0 / 211.0
- `net_delta`: 0.0 / 321.72 / -4.0 / 3828.0
- `ruff_errors`: 2.0 / 2.0 / 2.0 / 2.0
- `tests_failed`: 1.0 / 1.1 / 1.0 / 2.0
- `tests_passed`: 4775.0 / 4681.73 / 4583.0 / 4775.0
