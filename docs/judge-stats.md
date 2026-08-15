## CompletionJudge effectiveness (auto-updated)

**Runs**: 22 | **COMPLETE**: 1 (5%) | **INCOMPLETE**: 21 (95%, premature stops caught)
**Duration**: avg 8s / P95 15s | **Longest INCOMPLETE streak**: 21 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |
| 2026-08-15 | 1 | 0 | 0% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 21 (100% of incomplete)
- `delta`: 15 (71% of incomplete)
- `lint`: 7 (33% of incomplete)
- `singleton`: 6 (29% of incomplete)
- `docs`: 2 (10% of incomplete)
- `complex`: 2 (10% of incomplete)
- `cycle`: 2 (10% of incomplete)
- `index`: 2 (10% of incomplete)
- `audit`: 1 (5% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 20/21 (95%)
- `changelog`: 0/21 (0%)
- `complex`: 19/21 (90%)
- `cycle`: 19/21 (90%)
- `delta`: 7/22 (32%)
- `docs`: 20/22 (91%)
- `index`: 19/21 (90%)
- `lint`: 15/22 (68%)
- `singleton`: 15/21 (71%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 15
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 1.0 / 196.12 / 1.0 / 315.0
