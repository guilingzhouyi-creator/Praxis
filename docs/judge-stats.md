## CompletionJudge effectiveness (auto-updated)

**Runs**: 347 | **COMPLETE**: 43 (12%) | **PARTIAL**: 102 (29%, fast mode — checks skipped) | **INCOMPLETE**: 202 (58%, machine 'not done')
**Mode split**: full 120 (36% complete) / fast 227 (fast = at least one check skipped)
**Full-mode verdict rate**: 43/120 (36%) — the 'done' gold standard; mixed rates below include fast snapshots
**Telemetry snapshots excluded from rates**: 19 (push-both activity probes)
**Skipped tests notice**: tests skipped in 109 judge run(s) (full mode / WSL slice-serial required before merge)
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
| 2026-08-30 | 7 | 3 | 0 | 0% | 0% |

**Failures by check** (most frequent evidence gaps):
- `changelog`: 169 (84% of incomplete)
- `delta`: 77 (38% of incomplete)
- `lint`: 66 (33% of incomplete)
- `docs`: 57 (28% of incomplete)
- `tests`: 45 (22% of incomplete)
- `coverage`: 37 (18% of incomplete)
- `audit`: 27 (13% of incomplete)
- `singleton`: 17 (8% of incomplete)
- `cycle`: 14 (7% of incomplete)
- `complex`: 13 (6% of incomplete)
- `index`: 13 (6% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 251/278 (90%)
- `changelog`: 115/284 (40%)
- `complex`: 268/281 (95%)
- `coverage`: 85/122 (70%)
- `cycle`: 267/281 (95%)
- `delta`: 201/278 (72%)
- `docs`: 229/286 (80%)
- `index`: 331/344 (96%)
- `lint`: 220/286 (77%)
- `singleton`: 264/281 (94%)
- `tests`: 77/122 (63%)

**Skip distribution** (fast-mode blind spots — checks skipped most often):
- `tests`: skipped 225/227 (99%)
- `coverage`: skipped 225/227 (99%)
- `delta`: skipped 69/227 (30%)
- `audit`: skipped 68/227 (30%)
- `complex`: skipped 65/227 (29%)
- `cycle`: skipped 65/227 (29%)
- `singleton`: skipped 65/227 (29%)
- `changelog`: skipped 62/227 (27%)
- `docs`: skipped 61/227 (27%)
- `lint`: skipped 61/227 (27%)
- `index`: skipped 2/227 (1%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 67.2 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 11.54 / 0.0 / 316.0
- `net_delta`: 4846.0 / 2177.51 / -4.0 / 27424.0
- `ruff_errors`: 1.0 / 0.69 / 0.0 / 6.0
- `tests_failed`: 1.0 / 1.06 / 0.0 / 7.0
- `tests_passed`: 0.0 / 4751.22 / 0.0 / 5073.0
