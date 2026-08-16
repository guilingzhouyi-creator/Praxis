## CompletionJudge effectiveness (auto-updated)

**Runs**: 33 | **COMPLETE**: 2 (6%) | **INCOMPLETE**: 31 (94%, premature stops caught)
**Duration**: avg 10s / P95 20s | **Longest INCOMPLETE streak**: 29 consecutive
**Gate exemptions** (MERGE_GATE_SKIP in history): 2

| Date | Runs | Complete | Rate |
|---|---|---|---|
| 2026-08-14 | 21 | 1 | 5% |
| 2026-08-15 | 10 | 1 | 10% |
| 2026-08-16 | 2 | 0 | 0% |

**Failures by check** (which gate caught premature stops):
- `changelog`: 30 (97% of incomplete)
- `delta`: 25 (81% of incomplete)
- `lint`: 8 (26% of incomplete)
- `singleton`: 7 (23% of incomplete)
- `docs`: 3 (10% of incomplete)
- `complex`: 3 (10% of incomplete)
- `cycle`: 3 (10% of incomplete)
- `index`: 3 (10% of incomplete)
- `audit`: 1 (3% of incomplete)
- `tests`: 1 (3% of incomplete)
- `coverage`: 1 (3% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 31/32 (97%)
- `changelog`: 2/32 (6%)
- `complex`: 29/32 (91%)
- `coverage`: 0/1 (0%)
- `cycle`: 29/32 (91%)
- `delta`: 8/33 (24%)
- `docs`: 30/33 (91%)
- `index`: 29/32 (91%)
- `lint`: 25/33 (76%)
- `singleton`: 25/32 (78%)
- `tests`: 0/1 (0%)

**Failure pairs** (checks failing together):
- `changelog + delta`: 24
- `changelog + lint`: 8
- `changelog + singleton`: 7
- `delta + lint`: 5
- `lint + singleton`: 5

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `mega_funcs`: 0.0 / 16.21 / 0.0 / 173.0
- `net_delta`: 566.0 / 455.68 / -2.0 / 3828.0
