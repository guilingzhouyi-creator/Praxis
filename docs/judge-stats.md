## CompletionJudge effectiveness (auto-updated)

**Runs**: 30 | **COMPLETE**: 1 (3%) | **INCOMPLETE**: 29 (97%, premature stops caught)
**Duration**: avg 11s / P95 20s | **Longest INCOMPLETE streak**: 29 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |
| 2026-08-15 | 9 | 0 | 0% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 28 (97% of incomplete)
- `delta`: 23 (79% of incomplete)
- `lint`: 7 (24% of incomplete)
- `singleton`: 6 (21% of incomplete)
- `docs`: 2 (7% of incomplete)
- `complex`: 2 (7% of incomplete)
- `cycle`: 2 (7% of incomplete)
- `index`: 2 (7% of incomplete)
- `audit`: 1 (3% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 28/29 (97%)
- `changelog`: 1/29 (3%)
- `complex`: 27/29 (93%)
- `cycle`: 27/29 (93%)
- `delta`: 7/30 (23%)
- `docs`: 28/30 (93%)
- `index`: 27/29 (93%)
- `lint`: 23/30 (77%)
- `singleton`: 23/29 (79%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 22
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 0.0 / 8.44 / 0.0 / 9.0
- `net_delta`: 807.0 / 231.12 / -2.0 / 807.0
