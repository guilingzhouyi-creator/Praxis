## CompletionJudge effectiveness (auto-updated)

**Runs**: 25 | **COMPLETE**: 1 (4%) | **INCOMPLETE**: 24 (96%, premature stops caught)
**Duration**: avg 8s / P95 15s | **Longest INCOMPLETE streak**: 24 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |
| 2026-08-15 | 4 | 0 | 0% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 24 (100% of incomplete)
- `delta`: 18 (75% of incomplete)
- `lint`: 7 (29% of incomplete)
- `singleton`: 6 (25% of incomplete)
- `docs`: 2 (8% of incomplete)
- `complex`: 2 (8% of incomplete)
- `cycle`: 2 (8% of incomplete)
- `index`: 2 (8% of incomplete)
- `audit`: 1 (4% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 23/24 (96%)
- `changelog`: 0/24 (0%)
- `complex`: 22/24 (92%)
- `cycle`: 22/24 (92%)
- `delta`: 7/25 (28%)
- `docs`: 23/25 (92%)
- `index`: 22/24 (92%)
- `lint`: 18/25 (72%)
- `singleton`: 18/24 (75%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 18
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 183.0 / 168.91 / 1.0 / 315.0
