## CompletionJudge effectiveness (auto-updated)

**Runs**: 21 | **COMPLETE**: 1 (5%) | **INCOMPLETE**: 20 (95%, premature stops caught)
**Duration**: avg 8s / P95 15s | **Longest INCOMPLETE streak**: 20 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 20 (100% of incomplete)
- `delta`: 14 (70% of incomplete)
- `lint`: 7 (35% of incomplete)
- `singleton`: 6 (30% of incomplete)
- `docs`: 2 (10% of incomplete)
- `complex`: 2 (10% of incomplete)
- `cycle`: 2 (10% of incomplete)
- `index`: 2 (10% of incomplete)
- `audit`: 1 (5% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 19/20 (95%)
- `changelog`: 0/20 (0%)
- `complex`: 18/20 (90%)
- `cycle`: 18/20 (90%)
- `delta`: 7/21 (33%)
- `docs`: 19/21 (90%)
- `index`: 18/20 (90%)
- `lint`: 14/21 (67%)
- `singleton`: 14/20 (70%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 14
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 302.0 / 224.0 / 76.0 / 315.0
