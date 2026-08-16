## CompletionJudge effectiveness (auto-updated)

**Runs**: 65 | **COMPLETE**: 4 (6%) | **PARTIAL**: 9 (14%, fast mode — checks skipped) | **INCOMPLETE**: 52 (80%, machine 'not done')
**Mode split**: full 12 / fast 53 (fast = at least one check skipped)
**Duration** (full runs): avg 351s / P95 636s (12 runs) — fast runs: avg 14s / P95 90s (53 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 34 | 4 | 12% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 48 (92% of incomplete)
- `delta`: 32 (62% of incomplete)
- `docs`: 14 (27% of incomplete)
- `lint`: 14 (27% of incomplete)
- `singleton`: 13 (25% of incomplete)
- `complex`: 9 (17% of incomplete)
- `cycle`: 9 (17% of incomplete)
- `index`: 9 (17% of incomplete)
- `tests`: 5 (10% of incomplete)
- `coverage`: 2 (4% of incomplete)
- `audit`: 1 (2% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 2/47 (4%)
- `feature/perf-hotpath`: 1/4 (25%)
- `feature/judge-verdict-mode`: 1/4 (25%)
- `feature/test-runner-slicing`: 0/4 (0%)
- `feature/l3a-fidelity`: 0/4 (0%)
- `fix/runner-hang`: 0/2 (0%)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 61/62 (98%)
- `changelog`: 15/63 (24%)
- `complex`: 53/62 (85%)
- `coverage`: 10/12 (83%)
- `cycle`: 53/62 (85%)
- `delta`: 30/62 (48%)
- `docs`: 51/65 (78%)
- `index`: 53/62 (85%)
- `lint`: 51/65 (78%)
- `singleton`: 49/62 (79%)
- `tests`: 9/14 (64%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 31
- `changelog + lint`: 14
- `changelog + singleton`: 13
- `changelog + docs`: 11
- `lint + singleton`: 11

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 66.0 / 66.0 / 66.0 / 66.0
- `mega_funcs`: 211.0 / 32.04 / 0.0 / 211.0
- `net_delta`: 7.0 / 324.87 / -2.0 / 3828.0
- `tests_failed`: 1.0 / 1.0 / 1.0 / 1.0
- `tests_passed`: 4625.0 / 4599.25 / 4583.0 / 4625.0
