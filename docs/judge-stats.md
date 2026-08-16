## CompletionJudge effectiveness (auto-updated)

**Runs**: 61 | **COMPLETE**: 4 (7%) | **PARTIAL**: 9 (15%, fast mode — checks skipped) | **INCOMPLETE**: 48 (79%, machine 'not done')
**Mode split**: full 12 / fast 49 (fast = at least one check skipped)
**Duration** (full runs): avg 351s / P95 636s (12 runs) — fast runs: avg 9s / P95 15s (49 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 30 | 4 | 13% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 45 (94% of incomplete)
- `delta`: 30 (62% of incomplete)
- `lint`: 12 (25% of incomplete)
- `singleton`: 11 (23% of incomplete)
- `docs`: 11 (23% of incomplete)
- `complex`: 7 (15% of incomplete)
- `cycle`: 7 (15% of incomplete)
- `index`: 7 (15% of incomplete)
- `tests`: 3 (6% of incomplete)
- `coverage`: 2 (4% of incomplete)
- `audit`: 1 (2% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 2/45 (4%)
- `feature/perf-hotpath`: 1/4 (25%)
- `feature/judge-verdict-mode`: 1/4 (25%)
- `feature/test-runner-slicing`: 0/4 (0%)
- `feature/l3a-fidelity`: 0/4 (0%)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 59/60 (98%)
- `changelog`: 15/60 (25%)
- `complex`: 53/60 (88%)
- `coverage`: 10/12 (83%)
- `cycle`: 53/60 (88%)
- `delta`: 30/60 (50%)
- `docs`: 50/61 (82%)
- `index`: 53/60 (88%)
- `lint`: 49/61 (80%)
- `singleton`: 49/60 (82%)
- `tests`: 9/12 (75%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 29
- `changelog + lint`: 12
- `changelog + singleton`: 11
- `changelog + docs`: 9
- `lint + singleton`: 9

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 66.0 / 66.0 / 66.0 / 66.0
- `mega_funcs`: 205.0 / 24.43 / 0.0 / 205.0
- `net_delta`: 1252.0 / 346.79 / -2.0 / 3828.0
- `tests_failed`: 1.0 / 1.0 / 1.0 / 1.0
- `tests_passed`: 4600.0 / 4594.1 / 4583.0 / 4600.0
