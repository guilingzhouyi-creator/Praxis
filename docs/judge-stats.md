## CompletionJudge effectiveness (auto-updated)

**Runs**: 28 | **COMPLETE**: 1 (4%) | **INCOMPLETE**: 27 (96%, premature stops caught)
**Duration**: avg 8s / P95 15s | **Longest INCOMPLETE streak**: 27 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |
| 2026-08-15 | 7 | 0 | 0% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 27 (100% of incomplete)
- `delta`: 21 (78% of incomplete)
- `lint`: 7 (26% of incomplete)
- `singleton`: 6 (22% of incomplete)
- `docs`: 2 (7% of incomplete)
- `complex`: 2 (7% of incomplete)
- `cycle`: 2 (7% of incomplete)
- `index`: 2 (7% of incomplete)
- `audit`: 1 (4% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 26/27 (96%)
- `changelog`: 0/27 (0%)
- `complex`: 25/27 (93%)
- `cycle`: 25/27 (93%)
- `delta`: 7/28 (25%)
- `docs`: 26/28 (93%)
- `index`: 25/27 (93%)
- `lint`: 21/28 (75%)
- `singleton`: 21/27 (78%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 21
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 426.0 / 206.64 / 1.0 / 426.0
