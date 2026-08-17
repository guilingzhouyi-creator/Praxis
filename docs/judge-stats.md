## CompletionJudge effectiveness (auto-updated)

**Runs**: 73 | **COMPLETE**: 5 (7%) | **PARTIAL**: 12 (16%, fast mode — checks skipped) | **INCOMPLETE**: 56 (77%, machine 'not done')
**Mode split**: full 13 / fast 60 (fast = at least one check skipped)
**Duration** (full runs): avg 373s / P95 636s (13 runs) — fast runs: avg 14s / P95 90s (60 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 38 | 5 | 13% |
| 2026-08-17 | 4 | 0 | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 52 (93% of incomplete)
- `delta`: 33 (59% of incomplete)
- `lint`: 15 (27% of incomplete)
- `docs`: 14 (25% of incomplete)
- `singleton`: 13 (23% of incomplete)
- `complex`: 9 (16% of incomplete)
- `cycle`: 9 (16% of incomplete)
- `index`: 9 (16% of incomplete)
- `tests`: 5 (9% of incomplete)
- `audit`: 2 (4% of incomplete)
- `coverage`: 2 (4% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 3/53 (6%)
- `feature/perf-hotpath`: 1/4 (25%)
- `feature/judge-verdict-mode`: 1/4 (25%)
- `feature/test-runner-slicing`: 0/4 (0%)
- `feature/l3a-fidelity`: 0/4 (0%)
- `fix/runner-hang`: 0/2 (0%)
- `feature/test-opt`: 0/2 (0%)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 68/70 (97%)
- `changelog`: 19/71 (27%)
- `complex`: 61/70 (87%)
- `coverage`: 11/13 (85%)
- `cycle`: 61/70 (87%)
- `delta`: 37/70 (53%)
- `docs`: 59/73 (81%)
- `index`: 61/70 (87%)
- `lint`: 58/73 (79%)
- `singleton`: 57/70 (81%)
- `tests`: 10/15 (67%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 32
- `changelog + lint`: 15
- `changelog + singleton`: 13
- `changelog + docs`: 11
- `lint + singleton`: 11

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 67.0 / 66.09 / 66.0 / 67.0
- `mega_funcs`: 1.0 / 27.68 / 0.0 / 211.0
- `net_delta`: 0.0 / 316.41 / -2.0 / 3828.0
- `tests_failed`: 1.0 / 1.0 / 1.0 / 1.0
- `tests_passed`: 4626.0 / 4601.31 / 4583.0 / 4626.0
