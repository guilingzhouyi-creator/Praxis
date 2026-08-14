## CompletionJudge effectiveness (auto-updated)

**Runs**: 18 | **COMPLETE**: 1 (6%) | **INCOMPLETE**: 17 (94%, premature stops caught)
**Duration**: avg 8s / P95 20s | **Longest INCOMPLETE streak**: 17 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 18 | 1 | 6% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 17 (100% of incomplete)
- `delta`: 11 (65% of incomplete)
- `lint`: 7 (41% of incomplete)
- `singleton`: 6 (35% of incomplete)
- `docs`: 2 (12% of incomplete)
- `complex`: 2 (12% of incomplete)
- `cycle`: 2 (12% of incomplete)
- `index`: 2 (12% of incomplete)
- `audit`: 1 (6% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 16/17 (94%)
- `changelog`: 0/17 (0%)
- `complex`: 15/17 (88%)
- `cycle`: 15/17 (88%)
- `delta`: 7/18 (39%)
- `docs`: 16/18 (89%)
- `index`: 15/17 (88%)
- `lint`: 11/18 (61%)
- `singleton`: 11/17 (65%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 11
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 315.0 / 162.25 / 76.0 / 315.0
