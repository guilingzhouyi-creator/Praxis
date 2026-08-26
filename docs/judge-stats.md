## CompletionJudge effectiveness (auto-updated)

**Runs**: 248 | **COMPLETE**: 37 (15%) | **PARTIAL**: 31 (12%, fast mode — checks skipped) | **INCOMPLETE**: 180 (73%, machine 'not done')
**Mode split**: full 99 (37% complete) / fast 149 (fast = at least one check skipped)
**Full-mode verdict rate**: 37/99 (37%) — the 'done' gold standard; mixed rates below include fast snapshots
**Telemetry snapshots excluded from rates**: 1 (push-both activity probes)
**Skipped tests notice**: tests skipped in 31 judge run(s) (full mode / WSL slice-serial required before merge)
**Gate exemptions** (MERGE_GATE_SKIP commits in history): 11
**Waived delta passes**: 4 judge run(s) passed net-delta via MERGE_GATE_SKIP (not a qualifying delta)

| Date | Runs | Full Runs | Full Complete | Full Rate | Legacy Rate |
|---|---|---|---|---|---|
| 2026-08-14 | 21 | 0 | 0 | - | 0% |
| 2026-08-15 | 10 | 0 | 0 | - | 0% |
| 2026-08-16 | 38 | 13 | 5 | 38% | 13% |
| 2026-08-17 | 45 | 12 | 0 | 0% | 0% |
| 2026-08-18 | 22 | 12 | 4 | 33% | 18% |
| 2026-08-19 | 22 | 16 | 10 | 62% | 45% |
| 2026-08-20 | 8 | 8 | 4 | 50% | 50% |
| 2026-08-21 | 21 | 13 | 4 | 31% | 19% |
| 2026-08-22 | 25 | 17 | 7 | 41% | 28% |
| 2026-08-23 | 5 | 0 | 0 | - | 0% |
| 2026-08-24 | 4 | 0 | 0 | - | 0% |
| 2026-08-25 | 19 | 6 | 1 | 17% | 5% |
| 2026-08-26 | 8 | 2 | 2 | 100% | 25% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 154 (86% of incomplete)
- `delta`: 75 (42% of incomplete)
- `lint`: 60 (33% of incomplete)
- `docs`: 54 (30% of incomplete)
- `tests`: 32 (18% of incomplete)
- `coverage`: 28 (16% of incomplete)
- `audit`: 24 (13% of incomplete)
- `singleton`: 17 (9% of incomplete)
- `cycle`: 14 (8% of incomplete)
- `complex`: 13 (7% of incomplete)
- `index`: 13 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 218/242 (90%)
- `changelog`: 92/246 (37%)
- `complex`: 230/243 (95%)
- `coverage`: 72/100 (72%)
- `cycle`: 229/243 (94%)
- `delta`: 168/243 (69%)
- `docs`: 194/248 (78%)
- `index`: 232/245 (95%)
- `lint`: 188/248 (76%)
- `singleton`: 226/243 (93%)
- `tests`: 69/101 (68%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 67.02 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 12.95 / 0.0 / 316.0
- `net_delta`: 0.0 / 2145.98 / -4.0 / 27424.0
- `ruff_errors`: 0.0 / 1.13 / 0.0 / 6.0
- `tests_failed`: 0.0 / 1.34 / 0.0 / 7.0
- `tests_passed`: 5046.0 / 4809.87 / 2302.0 / 5065.0
