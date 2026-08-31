## CompletionJudge effectiveness (auto-updated)

**Runs**: 354 | **COMPLETE**: 43 (12%) | **PARTIAL**: 103 (29%, fast mode — checks skipped) | **INCOMPLETE**: 208 (59%, machine 'not done')
**Mode split**: full 126 (34% complete) / fast 228 (fast = at least one check skipped)
**Full-mode verdict rate**: 43/126 (34%) — the 'done' gold standard; mixed rates below include fast snapshots
**Telemetry snapshots excluded from rates**: 20 (push-both activity probes)
**Skipped tests notice**: tests skipped in 110 judge run(s) (full mode / WSL slice-serial required before merge)
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
| 2026-08-29 | 11 | 3 | 0 | 0% | 0% |
| 2026-08-30 | 11 | 7 | 0 | 0% | 0% |
| 2026-08-31 | 3 | 2 | 0 | 0% | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 173 (83% of incomplete)
- `delta`: 77 (37% of incomplete)
- `lint`: 69 (33% of incomplete)
- `docs`: 57 (27% of incomplete)
- `tests`: 51 (25% of incomplete)
- `coverage`: 40 (19% of incomplete)
- `audit`: 30 (14% of incomplete)
- `singleton`: 17 (8% of incomplete)
- `cycle`: 14 (7% of incomplete)
- `complex`: 13 (6% of incomplete)
- `index`: 13 (6% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 255/285 (89%)
- `changelog`: 118/291 (41%)
- `complex`: 275/288 (95%)
- `coverage`: 88/128 (69%)
- `cycle`: 274/288 (95%)
- `delta`: 208/285 (73%)
- `docs`: 236/293 (81%)
- `index`: 338/351 (96%)
- `lint`: 224/293 (76%)
- `singleton`: 271/288 (94%)
- `tests`: 77/128 (60%)

**Skip distribution** (fast-mode blind spots — checks skipped most often):
- `tests`: skipped 226/228 (99%)
- `coverage`: skipped 226/228 (99%)
- `delta`: skipped 69/228 (30%)
- `audit`: skipped 68/228 (30%)
- `complex`: skipped 65/228 (29%)
- `cycle`: skipped 65/228 (29%)
- `singleton`: skipped 65/228 (29%)
- `changelog`: skipped 62/228 (27%)
- `docs`: skipped 61/228 (27%)
- `lint`: skipped 61/228 (27%)
- `index`: skipped 2/228 (1%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 67.22 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 11.32 / 0.0 / 316.0
- `net_delta`: 0.0 / 2224.94 / -4.0 / 27424.0
- `ruff_errors`: 0.0 / 0.67 / 0.0 / 6.0
- `tests_failed`: 1.0 / 1.05 / 0.0 / 7.0
- `tests_passed`: 4311.0 / 4623.47 / 0.0 / 5073.0
