## CompletionJudge effectiveness (auto-updated)

**Runs**: 46 | **COMPLETE**: 3 (7%) | **PARTIAL**: 4 (9%, fast mode — checks skipped) | **INCOMPLETE**: 39 (85%, machine 'not done')
**Mode split**: full 10 / fast 36 (fast = at least one check skipped)
**Duration** (full runs): avg 358s / P95 591s (10 runs) — fast runs: avg 11s / P95 20s (36 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 15 | 3 | 20% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 37 (95% of incomplete)
- `delta`: 26 (67% of incomplete)
- `lint`: 8 (21% of incomplete)
- `singleton`: 7 (18% of incomplete)
- `docs`: 5 (13% of incomplete)
- `complex`: 3 (8% of incomplete)
- `cycle`: 3 (8% of incomplete)
- `index`: 3 (8% of incomplete)
- `tests`: 2 (5% of incomplete)
- `audit`: 1 (3% of incomplete)
- `coverage`: 1 (3% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 1/38 (3%)
- `feature/perf-hotpath`: 1/4 (25%)
- `feature/judge-verdict-mode`: 1/4 (25%)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 44/45 (98%)
- `changelog`: 8/45 (18%)
- `complex`: 42/45 (93%)
- `coverage`: 9/10 (90%)
- `cycle`: 42/45 (93%)
- `delta`: 20/46 (43%)
- `docs`: 41/46 (89%)
- `index`: 42/45 (93%)
- `lint`: 38/46 (83%)
- `singleton`: 38/45 (84%)
- `tests`: 8/10 (80%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 25
- `changelog + lint`: 8
- `changelog + singleton`: 7
- `delta + lint`: 5
- `lint + singleton`: 5

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 66.0 / 66.0 / 66.0 / 66.0
- `mega_funcs`: 1.0 / 9.91 / 0.0 / 173.0
- `net_delta`: 0.0 / 412.43 / -2.0 / 3828.0
- `tests_failed`: 1.0 / 1.0 / 1.0 / 1.0
- `tests_passed`: 4600.0 / 4593.44 / 4583.0 / 4600.0
