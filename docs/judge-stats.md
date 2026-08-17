## CompletionJudge effectiveness (auto-updated)

**Runs**: 113 | **COMPLETE**: 5 (4%) | **PARTIAL**: 17 (15%, fast mode — checks skipped) | **INCOMPLETE**: 91 (81%, machine 'not done')
**Mode split**: full 24 / fast 89 (fast = at least one check skipped)
**Duration** (full runs): avg 474s / P95 897s (24 runs) — fast runs: avg 21s / P95 118s (89 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 44 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 78 (86% of incomplete)
- `delta`: 47 (52% of incomplete)
- `docs`: 30 (33% of incomplete)
- `lint`: 30 (33% of incomplete)
- `singleton`: 14 (15% of incomplete)
- `tests`: 13 (14% of incomplete)
- `complex`: 10 (11% of incomplete)
- `cycle`: 10 (11% of incomplete)
- `index`: 10 (11% of incomplete)
- `coverage`: 9 (10% of incomplete)
- `audit`: 5 (5% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 3/80 (4%)
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
- `audit`: 105/110 (95%)
- `changelog`: 33/111 (30%)
- `complex`: 100/110 (91%)
- `coverage`: 15/24 (62%)
- `cycle`: 100/110 (91%)
- `delta`: 63/110 (57%)
- `docs`: 83/113 (73%)
- `index`: 100/110 (91%)
- `lint`: 83/113 (73%)
- `singleton`: 96/110 (87%)
- `tests`: 13/26 (50%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 43
- `changelog + docs`: 25
- `changelog + lint`: 25
- `docs + lint`: 17
- `delta + lint`: 16

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 67.0 / 63.15 / 0.0 / 67.0
- `mega_funcs`: 2.0 / 19.06 / 0.0 / 211.0
- `net_delta`: -3.0 / 342.11 / -3.0 / 3828.0
- `ruff_errors`: 2.0 / 2.0 / 2.0 / 2.0
- `tests_failed`: 1.0 / 1.1 / 1.0 / 2.0
- `tests_passed`: 4767.0 / 4665.14 / 4583.0 / 4767.0
