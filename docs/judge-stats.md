## CompletionJudge effectiveness (auto-updated)

**Runs**: 37 | **COMPLETE**: 4 (11%) | **INCOMPLETE**: 33 (89%, premature stops caught)
**Duration**: avg 51s / P95 555s | **Longest INCOMPLETE streak**: 29 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 2

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |
| 2026-08-15 | 10 | 1 | 10% |
| 2026-08-16 | 6 | 2 | 33% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 32 (97% of incomplete)
- `delta`: 25 (76% of incomplete)
- `lint`: 8 (24% of incomplete)
- `singleton`: 7 (21% of incomplete)
- `docs`: 3 (9% of incomplete)
- `complex`: 3 (9% of incomplete)
- `cycle`: 3 (9% of incomplete)
- `index`: 3 (9% of incomplete)
- `audit`: 1 (3% of incomplete)
- `tests`: 1 (3% of incomplete)
- `coverage`: 1 (3% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 35/36 (97%)
- `changelog`: 4/36 (11%)
- `complex`: 33/36 (92%)
- `coverage`: 3/4 (75%)
- `cycle`: 33/36 (92%)
- `delta`: 12/37 (32%)
- `docs`: 34/37 (92%)
- `index`: 33/36 (92%)
- `lint`: 29/37 (78%)
- `singleton`: 29/36 (81%)
- `tests`: 3/4 (75%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 24
- `changelog + lint`: 8
- `changelog + singleton`: 7
- `delta + lint`: 5
- `lint + singleton`: 5

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 66.0 / 66.0 / 66.0 / 66.0
- `mega_funcs`: 0.0 / 13.39 / 0.0 / 173.0
- `net_delta`: 566.0 / 455.68 / -2.0 / 3828.0
- `tests_failed`: 1.0 / 1.0 / 1.0 / 1.0
- `tests_passed`: 4595.0 / 4595.0 / 4595.0 / 4595.0
