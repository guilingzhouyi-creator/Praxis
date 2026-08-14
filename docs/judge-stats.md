## CompletionJudge effectiveness (auto-updated)

**Runs**: 20 | **COMPLETE**: 1 (5%) | **INCOMPLETE**: 19 (95%, premature stops caught)
**Duration**: avg 9s / P95 20s | **Longest INCOMPLETE streak**: 19 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 20 | 1 | 5% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 19 (100% of incomplete)
- `delta`: 13 (68% of incomplete)
- `lint`: 7 (37% of incomplete)
- `singleton`: 6 (32% of incomplete)
- `docs`: 2 (11% of incomplete)
- `complex`: 2 (11% of incomplete)
- `cycle`: 2 (11% of incomplete)
- `index`: 2 (11% of incomplete)
- `audit`: 1 (5% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 18/19 (95%)
- `changelog`: 0/19 (0%)
- `complex`: 17/19 (89%)
- `cycle`: 17/19 (89%)
- `delta`: 7/20 (35%)
- `docs`: 18/20 (90%)
- `index`: 17/19 (89%)
- `lint`: 13/20 (65%)
- `singleton`: 13/19 (68%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 13
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 302.0 / 211.0 / 76.0 / 315.0
