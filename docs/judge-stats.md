## CompletionJudge effectiveness (auto-updated)

**Runs**: 321 | **COMPLETE**: 43 (13%) | **PARTIAL**: 84 (26%, fast mode — checks skipped) | **INCOMPLETE**: 194 (60%, machine 'not done')
**Mode split**: full 114 (38% complete) / fast 207 (fast = at least one check skipped)
**Full-mode verdict rate**: 43/114 (38%) — the 'done' gold standard; mixed rates below include fast snapshots
**Telemetry snapshots excluded from rates**: 8 (push-both activity probes)
**Skipped tests notice**: tests skipped in 89 judge run(s) (full mode / WSL slice-serial required before merge)
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
| 2026-08-26 | 40 | 10 | 5 | 50% | 12% |
| 2026-08-27 | 32 | 6 | 2 | 33% | 6% |
| 2026-08-28 | 9 | 1 | 1 | 100% | 11% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 163 (84% of incomplete)
- `delta`: 76 (39% of incomplete)
- `lint`: 65 (34% of incomplete)
- `docs`: 57 (29% of incomplete)
- `tests`: 39 (20% of incomplete)
- `coverage`: 35 (18% of incomplete)
- `audit`: 25 (13% of incomplete)
- `singleton`: 17 (9% of incomplete)
- `cycle`: 14 (7% of incomplete)
- `complex`: 13 (7% of incomplete)
- `index`: 13 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 242/267 (91%)
- `changelog`: 110/273 (40%)
- `complex`: 257/270 (95%)
- `coverage`: 81/116 (70%)
- `cycle`: 256/270 (95%)
- `delta`: 191/267 (72%)
- `docs`: 218/275 (79%)
- `index`: 305/318 (96%)
- `lint`: 210/275 (76%)
- `singleton`: 253/270 (94%)
- `tests`: 77/116 (66%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 67.17 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 11.9 / 0.0 / 316.0
- `net_delta`: 1551.0 / 2122.38 / -4.0 / 27424.0
- `ruff_errors`: 0.0 / 0.78 / 0.0 / 6.0
- `tests_failed`: 0.0 / 1.06 / 0.0 / 7.0
- `tests_passed`: 5073.0 / 4818.55 / 2302.0 / 5073.0
