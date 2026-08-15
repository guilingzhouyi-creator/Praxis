## CompletionJudge effectiveness (auto-updated)

**Runs**: 27 | **COMPLETE**: 1 (4%) | **INCOMPLETE**: 26 (96%, premature stops caught)
**Duration**: avg 8s / P95 15s | **Longest INCOMPLETE streak**: 26 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 5

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |
| 2026-08-15 | 6 | 0 | 0% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 26 (100% of incomplete)
- `delta`: 20 (77% of incomplete)
- `lint`: 7 (27% of incomplete)
- `singleton`: 6 (23% of incomplete)
- `docs`: 2 (8% of incomplete)
- `complex`: 2 (8% of incomplete)
- `cycle`: 2 (8% of incomplete)
- `index`: 2 (8% of incomplete)
- `audit`: 1 (4% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 25/26 (96%)
- `changelog`: 0/26 (0%)
- `complex`: 24/26 (92%)
- `cycle`: 24/26 (92%)
- `delta`: 7/27 (26%)
- `docs`: 25/27 (93%)
- `index`: 24/26 (92%)
- `lint`: 20/27 (74%)
- `singleton`: 20/26 (77%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 20
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 9.0 / 9.0 / 9.0 / 9.0
- `net_delta`: 426.0 / 189.77 / 1.0 / 426.0
