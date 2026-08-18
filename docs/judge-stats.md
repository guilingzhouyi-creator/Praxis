## CompletionJudge effectiveness (auto-updated)

**Runs**: 130 | **COMPLETE**: 8 (6%) | **PARTIAL**: 17 (13%, fast mode — checks skipped) | **INCOMPLETE**: 105 (81%, machine 'not done')
**Mode split**: full 34 / fast 96 (fast = at least one check skipped)
**Duration** (full runs): avg 502s / P95 1015s (34 runs) — fast runs: avg 27s / P95 119s (96 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 45 | 0 | 0% |
| 2026-08-18 | 16 | 3 | 19% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 90 (86% of incomplete)
- `delta`: 50 (48% of incomplete)
- `docs`: 35 (33% of incomplete)
- `lint`: 32 (30% of incomplete)
- `singleton`: 15 (14% of incomplete)
- `tests`: 15 (14% of incomplete)
- `coverage`: 12 (11% of incomplete)
- `complex`: 11 (10% of incomplete)
- `cycle`: 11 (10% of incomplete)
- `index`: 11 (10% of incomplete)
- `audit`: 5 (5% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 4/91 (4%)
- `feature/test-matrix-prebuild`: 0/7 (0%)
- `feature/root-kernel-preflight`: 2/5 (40%)
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
- `audit`: 122/127 (96%)
- `changelog`: 38/128 (30%)
- `complex`: 116/127 (91%)
- `coverage`: 22/34 (65%)
- `cycle`: 116/127 (91%)
- `delta`: 77/127 (61%)
- `docs`: 95/130 (73%)
- `index`: 116/127 (91%)
- `lint`: 98/130 (75%)
- `singleton`: 112/127 (88%)
- `tests`: 21/36 (58%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 45
- `changelog + docs`: 28
- `changelog + lint`: 27
- `docs + lint`: 18
- `delta + lint`: 17

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 64.32 / 0.0 / 68.0
- `mega_funcs`: 2.0 / 18.35 / 0.0 / 211.0
- `net_delta`: 580.0 / 310.67 / -4.0 / 3828.0
- `ruff_errors`: 2.0 / 2.0 / 2.0 / 2.0
- `tests_failed`: 1.0 / 1.09 / 1.0 / 2.0
- `tests_passed`: 4809.0 / 4700.13 / 4583.0 / 4809.0
