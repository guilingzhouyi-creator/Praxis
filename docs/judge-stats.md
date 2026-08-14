## CompletionJudge effectiveness (auto-updated)

**Runs**: 19 | **COMPLETE**: 1 (5%) | **INCOMPLETE**: 18 (95%, premature stops caught)
**Duration**: avg 8s / P95 20s | **Longest INCOMPLETE streak**: 18 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 19 | 1 | 5% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 18 (100% of incomplete)
- `delta`: 12 (67% of incomplete)
- `lint`: 7 (39% of incomplete)
- `singleton`: 6 (33% of incomplete)
- `docs`: 2 (11% of incomplete)
- `complex`: 2 (11% of incomplete)
- `cycle`: 2 (11% of incomplete)
- `index`: 2 (11% of incomplete)
- `audit`: 1 (6% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 17/18 (94%)
- `changelog`: 0/18 (0%)
- `complex`: 16/18 (89%)
- `cycle`: 16/18 (89%)
- `delta`: 7/19 (37%)
- `docs`: 17/19 (89%)
- `index`: 16/18 (89%)
- `lint`: 12/19 (63%)
- `singleton`: 12/18 (67%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 12
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 315.0 / 192.8 / 76.0 / 315.0
