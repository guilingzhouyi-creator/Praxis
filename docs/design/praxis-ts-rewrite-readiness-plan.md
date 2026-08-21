# Plan — Source Code Optimization & TS Rewrite Readiness

## Current State

After two rounds of test optimization, the `feature/test-perf-slicing` branch
delivers the suite at **37.03s, 4927 passed, 0 failed** (baseline: 41.58s, 3
failed). The remaining slow points are now dominated by **gate/import scan
tests** and **script subprocesses** — both Python-specific patterns that
cannot be eliminated without addressing the source code they inspect.

## Remaining Slow Points (source-code side, not test side)

### Category A: Gate/Import Scan Tests (total ~20s, 10 tests)
These scan the entire source tree. Each is inherently Python-specific.

| Test | Time | What it scans | TS Rewrite Impact |
|---|---|---|---|
| `test_layer_imports` | 3.08s+2.99s+1.02s+0.91s | All `.py` files for upward imports | Full scan — must be rewritten as TS import graph checker |
| `test_params_guard` | 3.26s | All `.py` for hardcoded magic numbers | Depends on magic-number system design in TS |
| `test_process_port_usage` | 3.53s+1.42s | All `.py` for direct subprocess calls | TS equivalent: scan for `child_process.spawn` |
| `test_resets_completeness` | 2.10s | All `_RESETS` singleton entries | TS singleton pattern different |
| `test_single_execution_gate` | 1.97s | All `.py` for executor calls | TS equivalent: scan for `eval`/`new Function` |

### Category B: Script Subprocess Tests (total ~13.5s, 2 tests consumed)
These run `scripts/py/` via subprocess. The scripts are Python-specific.

| Test | Time | What it runs | TS Rewrite Impact |
|---|---|---|---|
| `test_scripts_collect_stats` | 7.30s | `collect_stats.py` — scans 598 .py files | Script must be rewritten in TS (or data-driven from JSON baseline) |
| `test_scripts_doc_stats_gate` | 6.19s | `check_doc_stats.py` — checks README drift | Same — needs TS equivalent |

### Category C: Integration Tests (total ~4.1s, 4 tests)
These exercise real boot/network/concurrency paths.

| Test | Time | What it does | TS Rewrite Impact |
|---|---|---|---|
| `test_boot_with_no_agents` | 1.64s | Real kernel boot | Architecture translates directly |
| `test_concurrent_dispatch_no_crash` | 1.63s | Real HTTP server + threads | Same pattern in TS (http + workers) |
| `test_init_services` | 0.84s | Real service init | Same |
| `test_githooks_commit_msg` | 0.97s | Runs bash hook + Python detect_agent | Hook + Python script → TS lint rule |

## Python-Specific Bindings (TS Rewrite Blockers)

### P0 — Must be addressed before TS rewrite

1. **`tests/conftest.py` singleton reset (`_RESETS` dict, 60+ entries)**
   - Python-specific: module path as string key, dynamic function dispatch
   - TS equivalent: module-level `reset()` exports or dependency injection
   - **Impact**: Every test depends on this; TS rewrite must replace the entire mechanism

2. **`tests/runner.py` — Python test runner**
   - Already improved, but still Python
   - TS equivalent: vitest/jest + custom runner, or Node.js CLI

3. **`scripts/py/` — Python scripts (6 scripts)**
   - `collect_stats.py`, `check_doc_stats.py`, `detect_agent.py`, `commit_scan.py`,
     `pre_commit_size_check.py`, `perf_quality.py`
   - TS rewrite: rewrite as Node.js scripts, or replace with data-driven JSON baselines
   - **Impact**: These scripts are referenced by Makefile, CI, and git hooks

4. **`.githooks/commit-msg` — bash hook that runs Python**
   - Calls `detect_agent.py` (Python) and `commit_scan.py` (Python)
   - TS rewrite: the hook must call a Node.js script instead of Python

### P1 — Architecture patterns that must be redesigned

5. **`l1.kernel.ports` — ABC port system (16 ports)**
   - Python-specific: ABC + typing + `get_process_port()` singleton
   - TS equivalent: interfaces + dependency injection
   - **Impact**: 16 *Port(ABC) abstractions + 16 adapters + 16 tests

6. **`conftest.py` `importlib.reload(_cmds_mod)`**
   - Python-only: reloads entire L2 command tree on every test
   - TS: Jest's `jest.resetModules()` is the closest equivalent
   - **Impact**: ~0.149s per test worker that imports L2 commands

7. **`l1.kernel.params/` — 12 magic-number modules**
   - Python constants → TS `const` or config files
   - **Impact**: 1136 constants must be migrated

### P2 — Convenient but not blocking

8. **Monkeypatch/mocker usage (~269 tests)**
   - `monkeypatch.setattr` → `jest.spyOn` / `vi.mock`
   - Well-understood mapping, low risk

9. **`l1.kernel.prompts` — prompt templates as `_DEFAULTS` dict**
   - Python dict → TS template literals or separate `.md` files

10. **`l3.tool_system.tool_pipeline` — 9-step execution pipeline**
    - Architecture translates directly; implementation is Python-specific

## Recommended Next Steps (ordered by TS-rewrite value)

### Step 1: Decouple script tests from Python runtime
- Replace `scripts/py/collect_stats.py` calls with pre-computed JSON snapshots
  (commit a `config/quality/stats-snapshot.json`, update via `make refresh-stats`)
- This eliminates the 2 largest remaining slow tests (7.30s + 6.19s) and
  removes the Python-script dependency from the test suite

### Step 2: Decouple git hooks from Python
- Rewrite `detect_agent.py` and `commit_scan.py` to read from
  `config/discovery/commits.yaml` directly (they're data-driven, not
  runtime-dependent)
- Make the `commit-msg` hook call a Node.js script (or read YAML directly)
- This removes the `test_githooks_commit_msg` 0.97s Python dependency

### Step 3: Parameterize gate scan tests
- The gate scan tests (test_layer_imports, test_params_guard, etc.) scan
  `.py` files. For TS rewrite, they must scan `.ts` files instead.
- **Option A**: Store the baseline as a JSON file and compare against it
  (faster, not Python-dependent)
- **Option B**: Keep the scan as a Makefile target (language-agnostic)

### Step 4: Replace conftest singleton reset mechanism
- Design a TS-compatible dependency injection pattern
- Each module exports a `reset()` function; the test runner calls it
- This is the foundation for the entire test infrastructure

### Step 5: Rewrite `tests/runner.py` as a Node.js CLI
- Preserve the `--maxfail`, `--keep-going`, `--once` patterns
- Use vitest or jest as the test runner
- Keep the slice-based organization

## Verification

After each step:
- `python -m pytest tests -q -n auto` → green (until Python tests are replaced)
- TS-equivalent gate tests pass
- `make precommit` green (both Python and TS gates)

## Branch Strategy

- Continue on `feature/test-perf-slicing` for Python-side optimizations
- Create `feature/tests-ts-rewrite` for the TypeScript rewrite itself
- Merge order: data-driven snapshots → Python script decoupling → TS rewrite