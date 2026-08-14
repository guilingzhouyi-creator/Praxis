## CompletionJudge effectiveness (auto-updated)

**Runs**: 17 | **COMPLETE**: 1 (6%) | **INCOMPLETE**: 16 (94%, premature stops caught)
**Duration**: avg 8s / P95 20s | **Longest INCOMPLETE streak**: 16 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 17 | 1 | 6% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 16 (100% of incomplete)
- `delta`: 10 (62% of incomplete)
- `lint`: 7 (44% of incomplete)
- `singleton`: 6 (38% of incomplete)
- `docs`: 2 (12% of incomplete)
- `complex`: 2 (12% of incomplete)
- `cycle`: 2 (12% of incomplete)
- `index`: 2 (12% of incomplete)
- `audit`: 1 (6% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 15/16 (94%)
- `changelog`: 0/16 (0%)
- `complex`: 14/16 (88%)
- `cycle`: 14/16 (88%)
- `delta`: 7/17 (41%)
- `docs`: 15/17 (88%)
- `index`: 14/16 (88%)
- `lint`: 10/17 (59%)
- `singleton`: 10/16 (62%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 10
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 76.0 / 111.33 / 76.0 / 129.0
