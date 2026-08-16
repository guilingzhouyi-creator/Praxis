## CompletionJudge effectiveness (auto-updated)

**Runs**: 64 | **COMPLETE**: 4 (6%) | **PARTIAL**: 9 (14%, fast mode — checks skipped) | **INCOMPLETE**: 51 (80%, machine 'not done')
**Mode split**: full 12 / fast 52 (fast = at least one check skipped)
**Duration** (full runs): avg 351s / P95 636s (12 runs) — fast runs: avg 14s / P95 90s (52 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 33 | 4 | 12% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 47 (92% of incomplete)
- `delta`: 31 (61% of incomplete)
- `docs`: 13 (25% of incomplete)
- `lint`: 13 (25% of incomplete)
- `singleton`: 12 (24% of incomplete)
- `complex`: 8 (16% of incomplete)
- `cycle`: 8 (16% of incomplete)
- `index`: 8 (16% of incomplete)
- `tests`: 5 (10% of incomplete)
- `coverage`: 2 (4% of incomplete)
- `audit`: 1 (2% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 2/46 (4%)
- `feature/perf-hotpath`: 1/4 (25%)
- `feature/judge-verdict-mode`: 1/4 (25%)
- `feature/test-runner-slicing`: 0/4 (0%)
- `feature/l3a-fidelity`: 0/4 (0%)
- `fix/runner-hang`: 0/2 (0%)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 60/61 (98%)
- `changelog`: 15/62 (24%)
- `complex`: 53/61 (87%)
- `coverage`: 10/12 (83%)
- `cycle`: 53/61 (87%)
- `delta`: 30/61 (49%)
- `docs`: 51/64 (80%)
- `index`: 53/61 (87%)
- `lint`: 51/64 (80%)
- `singleton`: 49/61 (80%)
- `tests`: 9/14 (64%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 30
- `changelog + lint`: 13
- `changelog + singleton`: 12
- `changelog + docs`: 10
- `lint + singleton`: 10

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 66.0 / 66.0 / 66.0 / 66.0
- `mega_funcs`: 211.0 / 28.31 / 0.0 / 211.0
- `net_delta`: 7.0 / 335.47 / -2.0 / 3828.0
- `tests_failed`: 1.0 / 1.0 / 1.0 / 1.0
- `tests_passed`: 4625.0 / 4599.25 / 4583.0 / 4625.0
