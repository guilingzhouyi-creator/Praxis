## CompletionJudge effectiveness (auto-updated)

**Runs**: 15 | **COMPLETE**: 1 (7%) | **INCOMPLETE**: 14 (93%, premature stops caught)
**Duration**: avg 8s / P95 20s | **Longest INCOMPLETE streak**: 14 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 15 | 1 | 7% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 14 (100% of incomplete)
- `delta`: 8 (57% of incomplete)
- `lint`: 7 (50% of incomplete)
- `singleton`: 6 (43% of incomplete)
- `docs`: 2 (14% of incomplete)
- `complex`: 2 (14% of incomplete)
- `cycle`: 2 (14% of incomplete)
- `index`: 2 (14% of incomplete)
- `audit`: 1 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 13/14 (93%)
- `changelog`: 0/14 (0%)
- `complex`: 12/14 (86%)
- `cycle`: 12/14 (86%)
- `delta`: 7/15 (47%)
- `docs`: 13/15 (87%)
- `index`: 12/14 (86%)
- `lint`: 8/15 (53%)
- `singleton`: 8/14 (57%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 8
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 129.0 / 129.0 / 129.0 / 129.0
