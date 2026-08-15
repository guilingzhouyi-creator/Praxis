## CompletionJudge effectiveness (auto-updated)

**Runs**: 31 | **COMPLETE**: 2 (6%) | **INCOMPLETE**: 29 (94%, premature stops caught)
**Duration**: avg 11s / P95 20s | **Longest INCOMPLETE streak**: 29 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 2

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |
| 2026-08-15 | 10 | 1 | 10% |

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
- `audit`: 29/30 (97%)
- `changelog`: 2/30 (7%)
- `complex`: 28/30 (93%)
- `cycle`: 28/30 (93%)
- `delta`: 8/31 (26%)
- `docs`: 29/31 (94%)
- `index`: 28/30 (93%)
- `lint`: 24/31 (77%)
- `singleton`: 24/30 (80%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 22
- `changelog + lint`: 7
- `changelog + singleton`: 6
- `delta + lint`: 4
- `lint + singleton`: 4

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 0.0 / 7.94 / 0.0 / 9.0
- `net_delta`: 3828.0 / 442.71 / -2.0 / 3828.0
