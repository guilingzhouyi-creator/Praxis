## CompletionJudge effectiveness (auto-updated)

**Runs**: 136 | **COMPLETE**: 9 (7%) | **PARTIAL**: 19 (14%, fast mode — checks skipped) | **INCOMPLETE**: 108 (79%, machine 'not done')
**Mode split**: full 37 / fast 99 (fast = at least one check skipped)
**Duration** (full runs): avg 511s / P95 1015s (37 runs) — fast runs: avg 27s / P95 119s (99 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 22 | 4 | 18% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 93 (86% of incomplete)
- `delta`: 50 (46% of incomplete)
- `docs`: 36 (33% of incomplete)
- `lint`: 32 (30% of incomplete)
- `singleton`: 15 (14% of incomplete)
- `tests`: 15 (14% of incomplete)
- `coverage`: 12 (11% of incomplete)
- `complex`: 11 (10% of incomplete)
- `cycle`: 11 (10% of incomplete)
- `index`: 11 (10% of incomplete)
- `audit`: 5 (5% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 4/94 (4%)
- `feature/test-matrix-prebuild`: 0/7 (0%)
- `feature/root-kernel-preflight`: 2/5 (40%)
- `feature/perf-hotpath`: 1/4 (25%)
- `feature/judge-verdict-mode`: 1/4 (25%)
- `feature/test-runner-slicing`: 0/4 (0%)
- `feature/l3a-fidelity`: 0/4 (0%)
- `feature/l3a-compression-migration`: 1/3 (33%)
- `fix/runner-hang`: 0/2 (0%)
- `feature/test-opt`: 0/2 (0%)
- `feature/test-opt-sweep`: 0/2 (0%)
- `feature/identity-uid`: 0/2 (0%)
- `feature/root-security-toolchain`: 0/2 (0%)
- `feature/ci-bench-smoke`: 0/1 (0%)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 128/133 (96%)
- `changelog`: 41/134 (31%)
- `complex`: 122/133 (92%)
- `coverage`: 25/37 (68%)
- `cycle`: 122/133 (92%)
- `delta`: 83/133 (62%)
- `docs`: 100/136 (74%)
- `index`: 122/133 (92%)
- `lint`: 104/136 (76%)
- `singleton`: 118/133 (89%)
- `tests`: 24/39 (62%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 45
- `changelog + docs`: 29
- `changelog + lint`: 27
- `docs + lint`: 18
- `delta + lint`: 17

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 67.0 / 64.58 / 0.0 / 68.0
- `mega_funcs`: 2.0 / 17.53 / 0.0 / 211.0
- `net_delta`: 0.0 / 311.82 / -4.0 / 3828.0
- `ruff_errors`: 2.0 / 2.0 / 2.0 / 2.0
- `tests_failed`: 1.0 / 1.09 / 1.0 / 2.0
- `tests_passed`: 4799.0 / 4708.85 / 4583.0 / 4809.0
