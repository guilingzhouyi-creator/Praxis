## CompletionJudge effectiveness (auto-updated)

**Runs**: 23 | **COMPLETE**: 1 (4%) | **INCOMPLETE**: 22 (96%, premature stops caught)
**Duration**: avg 8s / P95 15s | **Longest INCOMPLETE streak**: 22 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |
| 2026-08-15 | 2 | 0 | 0% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 22 (100% of incomplete)
- `delta`: 16 (73% of incomplete)
- `lint`: 7 (32% of incomplete)
- `singleton`: 6 (27% of incomplete)
- `docs`: 2 (9% of incomplete)
- `complex`: 2 (9% of incomplete)
- `cycle`: 2 (9% of incomplete)
- `index`: 2 (9% of incomplete)
- `audit`: 1 (5% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 21/22 (95%)
- `changelog`: 0/22 (0%)
- `complex`: 20/22 (91%)
- `cycle`: 20/22 (91%)
- `delta`: 7/23 (30%)
- `docs`: 21/23 (91%)
- `index`: 20/22 (91%)
- `lint`: 16/23 (70%)
- `singleton`: 16/22 (73%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 16
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 1.0 / 174.44 / 1.0 / 315.0
