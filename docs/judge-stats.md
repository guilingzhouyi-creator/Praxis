## CompletionJudge effectiveness (auto-updated)

**Runs**: 111 | **COMPLETE**: 5 (5%) | **PARTIAL**: 17 (15%, fast mode — checks skipped) | **INCOMPLETE**: 89 (80%, machine 'not done')
**Mode split**: full 23 / fast 88 (fast = at least one check skipped)
**Duration** (full runs): avg 456s / P95 740s (23 runs) — fast runs: avg 20s / P95 118s (88 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 42 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 76 (85% of incomplete)
- `delta`: 46 (52% of incomplete)
- `docs`: 29 (33% of incomplete)
- `lint`: 29 (33% of incomplete)
- `singleton`: 14 (16% of incomplete)
- `tests`: 13 (15% of incomplete)
- `complex`: 10 (11% of incomplete)
- `cycle`: 10 (11% of incomplete)
- `index`: 10 (11% of incomplete)
- `coverage`: 9 (10% of incomplete)
- `audit`: 5 (6% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 3/78 (4%)
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
- `audit`: 103/108 (95%)
- `changelog`: 33/109 (30%)
- `complex`: 98/108 (91%)
- `coverage`: 14/23 (61%)
- `cycle`: 98/108 (91%)
- `delta`: 62/108 (57%)
- `docs`: 82/111 (74%)
- `index`: 98/108 (91%)
- `lint`: 82/111 (74%)
- `singleton`: 94/108 (87%)
- `tests`: 12/25 (48%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 42
- `changelog + docs`: 24
- `changelog + lint`: 24
- `docs + lint`: 17
- `delta + lint`: 16

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 67.0 / 62.95 / 0.0 / 67.0
- `mega_funcs`: 2.0 / 19.42 / 0.0 / 211.0
- `net_delta`: -1.0 / 348.38 / -2.0 / 3828.0
- `ruff_errors`: 2.0 / 2.0 / 2.0 / 2.0
- `tests_failed`: 1.0 / 1.1 / 1.0 / 2.0
- `tests_passed`: 4767.0 / 4660.29 / 4583.0 / 4767.0
