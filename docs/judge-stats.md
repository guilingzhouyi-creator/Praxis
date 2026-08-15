## CompletionJudge effectiveness (auto-updated)

**Runs**: 29 | **COMPLETE**: 1 (3%) | **INCOMPLETE**: 28 (97%, premature stops caught)
**Duration**: avg 11s / P95 20s | **Longest INCOMPLETE streak**: 28 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |
| 2026-08-15 | 8 | 0 | 0% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 28 (100% of incomplete)
- `delta`: 22 (79% of incomplete)
- `lint`: 7 (25% of incomplete)
- `singleton`: 6 (21% of incomplete)
- `docs`: 2 (7% of incomplete)
- `complex`: 2 (7% of incomplete)
- `cycle`: 2 (7% of incomplete)
- `index`: 2 (7% of incomplete)
- `audit`: 1 (4% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 27/28 (96%)
- `changelog`: 0/28 (0%)
- `complex`: 26/28 (93%)
- `cycle`: 26/28 (93%)
- `delta`: 7/29 (24%)
- `docs`: 27/29 (93%)
- `index`: 26/28 (93%)
- `lint`: 22/29 (76%)
- `singleton`: 22/28 (79%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 22
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: -2.0 / 192.73 / -2.0 / 426.0
