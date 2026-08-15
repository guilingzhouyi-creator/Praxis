## CompletionJudge effectiveness (auto-updated)

**Runs**: 26 | **COMPLETE**: 1 (4%) | **INCOMPLETE**: 25 (96%, premature stops caught)
**Duration**: avg 8s / P95 15s | **Longest INCOMPLETE streak**: 25 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |
| 2026-08-15 | 5 | 0 | 0% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 25 (100% of incomplete)
- `delta`: 19 (76% of incomplete)
- `lint`: 7 (28% of incomplete)
- `singleton`: 6 (24% of incomplete)
- `docs`: 2 (8% of incomplete)
- `complex`: 2 (8% of incomplete)
- `cycle`: 2 (8% of incomplete)
- `index`: 2 (8% of incomplete)
- `audit`: 1 (4% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 24/25 (96%)
- `changelog`: 0/25 (0%)
- `complex`: 23/25 (92%)
- `cycle`: 23/25 (92%)
- `delta`: 7/26 (27%)
- `docs`: 24/26 (92%)
- `index`: 23/25 (92%)
- `lint`: 19/26 (73%)
- `singleton`: 19/25 (76%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 19
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 183.0 / 170.08 / 1.0 / 315.0
