## CompletionJudge effectiveness (auto-updated)

**Runs**: 337 | **COMPLETE**: 43 (13%) | **PARTIAL**: 99 (29%, fast mode — checks skipped) | **INCOMPLETE**: 195 (58%, machine 'not done')
**Mode split**: full 115 (37% complete) / fast 222 (fast = at least one check skipped)
**Full-mode verdict rate**: 43/115 (37%) — the 'done' gold standard; mixed rates below include fast snapshots
**Telemetry snapshots excluded from rates**: 16 (push-both activity probes)
**Skipped tests notice**: tests skipped in 104 judge run(s) (full mode / WSL slice-serial required before merge)
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
| 2026-08-28 | 17 | 1 | 1 | 100% | 6% |
| 2026-08-29 | 8 | 1 | 0 | 0% | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 164 (84% of incomplete)
- `delta`: 77 (39% of incomplete)
- `lint`: 65 (33% of incomplete)
- `docs`: 57 (29% of incomplete)
- `tests`: 40 (21% of incomplete)
- `coverage`: 36 (18% of incomplete)
- `audit`: 25 (13% of incomplete)
- `singleton`: 17 (9% of incomplete)
- `cycle`: 14 (7% of incomplete)
- `complex`: 13 (7% of incomplete)
- `index`: 13 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 243/268 (91%)
- `changelog`: 110/274 (40%)
- `complex`: 258/271 (95%)
- `coverage`: 81/117 (69%)
- `cycle`: 257/271 (95%)
- `delta`: 191/268 (71%)
- `docs`: 219/276 (79%)
- `index`: 321/334 (96%)
- `lint`: 211/276 (76%)
- `singleton`: 254/271 (94%)
- `tests`: 77/117 (66%)

**Skip distribution** (fast-mode blind spots — checks skipped most often):
- `tests`: skipped 220/222 (99%)
- `coverage`: skipped 220/222 (99%)
- `delta`: skipped 69/222 (31%)
- `audit`: skipped 68/222 (31%)
- `complex`: skipped 65/222 (29%)
- `cycle`: skipped 65/222 (29%)
- `singleton`: skipped 65/222 (29%)
- `changelog`: skipped 62/222 (28%)
- `docs`: skipped 61/222 (27%)
- `lint`: skipped 61/222 (27%)
- `index`: skipped 2/222 (1%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 67.17 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 11.87 / 0.0 / 316.0
- `net_delta`: 595.0 / 2108.98 / -4.0 / 27424.0
- `ruff_errors`: 0.0 / 0.77 / 0.0 / 6.0
- `tests_failed`: 1.0 / 1.06 / 0.0 / 7.0
- `tests_passed`: 4301.0 / 4813.89 / 2302.0 / 5073.0
