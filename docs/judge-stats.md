## CompletionJudge effectiveness (auto-updated)

**Runs**: 24 | **COMPLETE**: 1 (4%) | **INCOMPLETE**: 23 (96%, premature stops caught)
**Duration**: avg 8s / P95 15s | **Longest INCOMPLETE streak**: 23 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |
| 2026-08-15 | 3 | 0 | 0% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 23 (100% of incomplete)
- `delta`: 17 (74% of incomplete)
- `lint`: 7 (30% of incomplete)
- `singleton`: 6 (26% of incomplete)
- `docs`: 2 (9% of incomplete)
- `complex`: 2 (9% of incomplete)
- `cycle`: 2 (9% of incomplete)
- `index`: 2 (9% of incomplete)
- `audit`: 1 (4% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 22/23 (96%)
- `changelog`: 0/23 (0%)
- `complex`: 21/23 (91%)
- `cycle`: 21/23 (91%)
- `delta`: 7/24 (29%)
- `docs`: 22/24 (92%)
- `index`: 21/23 (91%)
- `lint`: 17/24 (71%)
- `singleton`: 17/23 (74%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 17
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 105.0 / 167.5 / 1.0 / 315.0
