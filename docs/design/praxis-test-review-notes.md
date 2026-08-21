# Test Suite Review Notes — completeness & performance audit

Audit date: 2026-08-21, branch `feature/test-perf-slicing`, baseline HEAD
`8c936079`, plain shell under WSL (32 vCPU).

## Completeness (against AGENTS.md / docs)

| Dimension | Result |
|---|---|
| src→test reference coverage | **583/583 src modules referenced** (AST reverse-index audit, 0 missing) |
| Layer-import gates | `tests/infra/test_layer_imports.py` — 9 gate tests, green |
| Singleton reset coverage | `tests/conftest.py _RESETS` (60+ entries) + `test_resets_completeness.py`, green |
| Params/magic-number gates | `test_params_guard/integrity/compliance.py`, green |
| Collection | **4933 collected** (`-n auto --dist loadfile`), 4927 passed / 3 skipped / 3 failed in single process at baseline |
| Failing (single-process) | `test_githooks_commit_msg::test_valid_conventional_passes` (env), `test_skill_posture` × 2 (serially reproducible — regression or fixture bug) |
| Reporter gap | `.github/workflows/test.yml` passes `--maxfail=5`; `runner.py` silently drops unknown `--*` flags |

## Performance (single-process `-n auto`, 32 workers)

- Full suite: **41.6s wall**, 13.5 min CPU.
- Per-slice runner `--parallel` (independent process per slice): `infra`
  slice alone = **54.75s** for 302 tests → worse than whole suite in one
  process. Repeated 32-worker spawns under WSL dominate.
- Top hotspots (single run `--durations=10`):

| Test | Time | Cause |
|---|---|---|
| `l3/tools/test_git.py::TestGitPush::test_push` | 11.6s | real `git push` (network/remote wait) |
| `l3/bus/test_task_bus_cron.py::TestTaskBusSignature::test_payload_has_hmac_when_secret_set` | 5.1s | real HTTP connect/refuse (`localhost:1`) |
| `infra/test_scripts_collect_stats.py` (6 tests) | 2.0–5.9s ea | subprocess script runs (documented) |
| `infra/test_scripts_doc_stats_gate.py` (4 tests) | 2.5–4.6s ea | subprocess script runs (documented) |

## Environment-dependent failures (not code regressions)

- `test_githooks_commit_msg::test_valid_conventional_passes`: commit-msg
  hook rejects because `detect_agent.py` cannot confirm the model without a
  live harness session log. Passes under DSH/CI; fails in plain shell.
  → plan: skip when evidence unavailable.
- `test_skill_posture` × 2: serially reproducible; investigate during the
  plan run.