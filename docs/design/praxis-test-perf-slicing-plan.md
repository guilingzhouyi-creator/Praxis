# Plan — Test Suite Performance & Slice Acceleration

Branch: `feature/test-perf-slicing` (worktree `/home/guiling/dev/praxis-test-perf`)
Baseline HEAD: `8c936079`

## Context

Per review (see `docs/design/praxis-test-review-notes.md`), the suite runs
**4933 tests in ~41.6s** in a single pytest process with `-n auto` (32
workers). The existing per-slice runner (`tests/runner.py`) spawns an
independent pytest process per slice — measuring `infra` alone under
`--parallel` took **54.75s** for 302 tests, i.e. worse than the whole suite
in one process. Root causes:

1. **Repeated worker spawn**: every slice re-inits 32 xdist workers (slow
   under WSL).
2. **Silent CLI contract bug**: `.github/workflows/test.yml` passes
   `--maxfail=5` but `runner.py` does not parse it — the flag is silently
   dropped (falls into the `--` filter and is discarded).
3. **Fail-fast full runs**: `_run_full` stops at the first failing slice,
   so CI never sees the full failure set in one run.
4. **Slow hotspot tests** (measured, single full run `--durations=10`):
   - `tests/l3/tools/test_git.py::TestGitPush::test_push` — **11.6s**
     (real `git push` touching a remote).
   - `tests/l3/bus/test_task_bus_cron.py::test_payload_has_hmac_when_secret_set`
     — **5.1s** (real HTTP connect/refuse on `localhost:1`).
   - `tests/infra/test_scripts_collect_stats.py` — 6 tests at 2–5.9s each
     (subprocess script runs; acceptable, documented as-is).
   - `tests/infra/test_scripts_doc_stats_gate.py` — 4 tests at 2.5s each
     (subprocess script runs; acceptable, documented as-is).
5. **Environment-dependent failures** (must not block the suite):
   - `tests/infra/test_githooks_commit_msg.py::test_valid_conventional_passes`
     — commit-msg hook rejects because `detect_agent.py` cannot confirm the
     model without a live harness session log (works in DSH/CI, fails in a
     plain shell). Needs an explicit skip when attribution evidence is
     unavailable.
   - `tests/l3/tools/test_skill_posture.py` — 2 test failures reproducing
     serially. Investigate: likely fixture/state isolation or posture
     ordering bug.

## Goals

- **G1 (correctness)**: make `runner.py` honor `--maxfail N` and add a
  `--keep-going` mode that runs all slices and reports every failure.
- **G2 (speed)**: cut full-suite wall time by removing the worst hotspot
  waits; single-process full run stays the fastest path via a new `--once`
  mode.
- **G3 (stability)**: environment-dependent failures skip instead of fail;
  `test_skill_posture` regression fixed (or root-caused as test bug and
  corrected).

## Execution Slices

### Slice 1 — runner.py CLI contract (`tests/runner.py`)

- Add `--maxfail N` parsing: pass `--maxfail=N` to pytest in every
  invocation; unknown `--*` flags fail loudly instead of being silently
  dropped.
- Add `--keep-going`: in full-run mode, run every slice, collect exit codes,
  print a summary and exit non-zero if any failed (default remains
  fail-fast for backward compatibility).
- Add `--once`: collect all slice targets into one pytest process command
  (`-n auto --dist loadfile`), the fastest full-suite path (~41s).
- Verify: `tests/runner.py --list-slices`, `--once`, `--keep-going` all run;
  `test.yml` interfaces hold (`--slice X --maxfail=5`).

### Slice 2 — `test_git.py::test_push` (11.6s → <1s)

- Replace the unconditional `git_push({}, "agent-a")` (real remote push)
  with a tmp-dir repo + `monkeypatch`/stub of the remote, or assert against
  `_git` failure path using an empty local repo (no network).
- Keep coverage intent: push returns a dict; failure path is safe.
- Verify: `-m pytest tests/l3/tools/test_git.py -q` green, matching duration
  < 1s; full-suite durations show drop.

### Slice 3 — `test_task_bus_cron.py` HMAC (5.1s → <1s)

- Stub HTTP dispatch: monkeypatch `urllib.request.urlopen`/the transport
  used by `_dispatch_one` so the HMAC header construction is verified without
  a real connect/refuse wait.
- Keep assertions (`result is False`, header/secret handling).
- Verify: `-m pytest tests/l3/bus/test_task_bus_cron.py -q` green, < 1s.

### Slice 4 — githooks environment skip

- In `tests/infra/test_githooks_commit_msg.py`, run
  `scripts/py/detect_agent.py --json` once (cached) and
  `pytest.skip(...)` the attribution-dependent test when evidence is
  unavailable (`detection unavailable`), unless
  `PRAXIS_SKIP_AUTHOR_CHECK=1`. Other hook-grammar tests stay enforced.
- Verify: hook tests green in plain shell (skip) and in DSH (run).

### Slice 5 — `test_skill_posture` regression

- Reproduce serially, trace `_inject_extra_context` + posture gate with
  debug prints or reasoning; identify whether the bug is in
  `l3/agent/agent_loop.py` posture gating or the test's fixture setup.
- Fix the true root cause (code or test); do not weaken assertions.
- Verify: both failing tests + neighbors green; full l3-fast slice green.

### Slice 6 — docs & gates refresh

- Update `tests/runner.py` docstring with `--maxfail` / `--keep-going` /
  `--once` usage.
- Refresh `docs/architecture/perf-baseline.md` note if suite timings claim
  change (only if baseline doc mentions suite wall time).
- Final gates: `make lint`, worktree clean, full suite green.

## Verification (completion criteria)

1. `python -m pytest tests -q --durations=10` → all green, total < 45s.
2. `tests/runner.py --once` and `tests/runner.py --keep-going` exit 0.
3. `tests/runner.py --slice infra --maxfail=5` passes through the flag
   (observable via `-p no:cacheprovider` verbose or help).
4. Duration deltas: `test_git::test_push`, cron HMAC each < 1.5s.
5. `bash scripts/sh/verify-completion.sh` COMPLETE (11 dimensions).