## CompletionJudge effectiveness (auto-updated)

**Runs**: 48 | **COMPLETE**: 4 (8%) | **PARTIAL**: 4 (8%, fast mode — checks skipped) | **INCOMPLETE**: 40 (83%, machine 'not done')
**Mode split**: full 11 / fast 37 (fast = at least one check skipped)
**Duration** (full runs): avg 383s / P95 636s (11 runs) — fast runs: avg 10s / P95 20s (37 runs)
**Longest INCOMPLETE streak**: 29 consecutive

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0% |
| 2026-08-15 | 10 | 0 | 0% |
| 2026-08-16 | 17 | 4 | 24% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 38 (95% of incomplete)
- `delta`: 26 (65% of incomplete)
- `lint`: 9 (22% of incomplete)
- `singleton`: 8 (20% of incomplete)
- `docs`: 6 (15% of incomplete)
- `complex`: 4 (10% of incomplete)
- `cycle`: 4 (10% of incomplete)
- `index`: 4 (10% of incomplete)
- `tests`: 2 (5% of incomplete)
- `audit`: 1 (2% of incomplete)
- `coverage`: 1 (2% of incomplete)

**Completion rate by branch** (weak-link detection):
- `main`: 2/40 (5%)
- `feature/perf-hotpath`: 1/4 (25%)
- `feature/judge-verdict-mode`: 1/4 (25%)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 46/47 (98%)
- `changelog`: 9/47 (19%)
- `complex`: 43/47 (91%)
- `coverage`: 10/11 (91%)
- `cycle`: 43/47 (91%)
- `delta`: 22/48 (46%)
- `docs`: 42/48 (88%)
- `index`: 43/47 (91%)
- `lint`: 39/48 (81%)
- `singleton`: 39/47 (83%)
- `tests`: 9/11 (82%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 25
- `changelog + lint`: 9
- `changelog + singleton`: 8
- `lint + singleton`: 6
- `changelog + docs`: 5

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 66.0 / 66.0 / 66.0 / 66.0
- `mega_funcs`: 205.0 / 15.38 / 0.0 / 205.0
- `net_delta`: 0.0 / 412.43 / -2.0 / 3828.0
- `tests_failed`: 1.0 / 1.0 / 1.0 / 1.0
- `tests_passed`: 4600.0 / 4594.1 / 4583.0 / 4600.0
