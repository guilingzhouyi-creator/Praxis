## CompletionJudge effectiveness (auto-updated)

**Runs**: 280 | **COMPLETE**: 40 (14%) | **PARTIAL**: 53 (19%, fast mode — checks skipped) | **INCOMPLETE**: 187 (67%, machine 'not done')
**Mode split**: full 107 (37% complete) / fast 173 (fast = at least one check skipped)
**Full-mode verdict rate**: 40/107 (37%) — the 'done' gold standard; mixed rates below include fast snapshots
**Telemetry snapshots excluded from rates**: 2 (push-both activity probes)
**Skipped tests notice**: tests skipped in 55 judge run(s) (full mode / WSL slice-serial required before merge)
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

**Failures by check** (most frequent evidence gaps):
- `changelog`: 158 (84% of incomplete)
- `delta`: 76 (41% of incomplete)
- `lint`: 60 (32% of incomplete)
- `docs`: 56 (30% of incomplete)
- `tests`: 36 (19% of incomplete)
- `coverage`: 32 (17% of incomplete)
- `audit`: 25 (13% of incomplete)
- `singleton`: 17 (9% of incomplete)
- `cycle`: 14 (7% of incomplete)
- `complex`: 13 (7% of incomplete)
- `index`: 13 (7% of incomplete)

**Check pass rate** (over executed runs — ratchet evidence):
- `audit`: 233/258 (90%)
- `changelog`: 104/262 (40%)
- `complex`: 246/259 (95%)
- `coverage`: 76/108 (70%)
- `cycle`: 245/259 (95%)
- `delta`: 180/256 (70%)
- `docs`: 208/264 (79%)
- `index`: 264/277 (95%)
- `lint`: 204/264 (77%)
- `singleton`: 242/259 (93%)
- `tests`: 73/109 (67%)

**Numeric metrics** (latest / avg / min / max):
- `audit_vulns`: 0.0 / 0.0 / 0.0 / 0.0
- `coverage_pct`: 68.0 / 67.1 / 0.0 / 69.0
- `mega_funcs`: 3.0 / 12.3 / 0.0 / 316.0
- `net_delta`: 1551.0 / 2122.38 / -4.0 / 27424.0
- `ruff_errors`: 0.0 / 0.84 / 0.0 / 6.0
- `tests_failed`: 1.0 / 1.18 / 0.0 / 7.0
- `tests_passed`: 4667.0 / 4813.44 / 2302.0 / 5065.0
