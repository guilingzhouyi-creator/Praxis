## CompletionJudge effectiveness (auto-updated)

**Runs**: 16 | **COMPLETE**: 1 (6%) | **INCOMPLETE**: 15 (94%, premature stops caught)
**Duration**: avg 8s / P95 20s | **Longest INCOMPLETE streak**: 15 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 16 | 1 | 6% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 15 (100% of incomplete)
- `delta`: 9 (60% of incomplete)
- `lint`: 7 (47% of incomplete)
- `singleton`: 6 (40% of incomplete)
- `docs`: 2 (13% of incomplete)
- `complex`: 2 (13% of incomplete)
- `cycle`: 2 (13% of incomplete)
- `index`: 2 (13% of incomplete)
- `audit`: 1 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 14/15 (93%)
- `changelog`: 0/15 (0%)
- `complex`: 13/15 (87%)
- `cycle`: 13/15 (87%)
- `delta`: 7/16 (44%)
- `docs`: 14/16 (88%)
- `index`: 13/15 (87%)
- `lint`: 9/16 (56%)
- `singleton`: 9/15 (60%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 9
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 129.0 / 129.0 / 129.0 / 129.0
