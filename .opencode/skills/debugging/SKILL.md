---
name: debugging
description: Use when diagnosing bugs or test failures in the Praxis codebase — trace_id propagation through request/agent/tool/error paths, kernel syscall audit trails, error_bus, structured dict error returns, singleton pollution, and the test runner batches.
---

## Overview

Systematic debugging workflow for Praxis. The codebase is 5-layer (L1 kernel → L5 CLI) with strict import rules and heavy singleton use — most failures fall into a few recognizable categories. Work from the trace_id down, not from symptoms up.

## 1. Follow the Trace ID

- One unified trace id flows request → agent → tool → error via `src/l3/error_bus/core.py`: `get_trace_id()` / `set_trace_id()` / `trace_scope`. Never mint new ids in new code paths — propagate the existing one.
- When a failure surfaces, the trace_id in the error connects the failing step to the originating request; use it to correlate logs (kernel audit trail, tool pipeline gates, error bus events).

## 2. Classify the Failure

- **Setup/pollution**: module-level singletons (`get_*()` accessors) are reset by `tests/conftest.py` `_RESETS` before each test. If tests pass alone but fail in sequence, a singleton is missing from `_RESETS`. Add the service's reset function there.
- **Layer violation**: if an import fails with a cycle or an unexpected cross-layer import, check the import rules (L5→L4→L3→L2→L1 one-way). `python -m pytest tests/infra/test_layer_imports.py -x -q` flags new violations; pre-existing ones are allowlisted.
- **Constants drift**: `tests/infra/test_params_compliance.py` (strict) catches hardcoded magic numbers that should live in `src/l1/kernel/params/`. Symmetric bug: params changed but references not regenerated (`make doc-stats`).
- **Hook rejection**: a commit/merge rejected by git is usually the mainline whitelist or commit-msg rules — see the git-workflow skill.
- **Contract mismatch**: API 4xx on valid calls — route not in the manifest (`python -m l4.api.api_endpoints`), or versioned path drifted (`_strip_version`).

## 3. Trace the Execution Path

- **Kernel**: every operation goes through `syscall(op, ...)` (audited, structured error codes). Check the audit trail for the op that failed and its error code.
- **Tool path**: `src/l3/tool_system/tool_pipeline.py` 9-step pipeline with per-phase gate traces — enable step tracing to find which phase dropped the call.
- **Card path**: CardRegistry lifecycle (submit → dispatch → complete/fail); execution_engine recovery modes (abort/retry/skip/rollback) explain "silently skipped" steps.
- **Sandbox edits**: all agent writes land in the sandbox with per-hunk attribution (`agent_id`, `tool_name`, `task_id`, `modified_at`). "My edit disappeared" is usually a parallel-agent hunk or a sandbox cache issue (`.praxis/sandbox_state.json` in `data_dir`).

## 4. Reproduce with the Right Runner

- Fast core: `python tests/runner.py --batch 1` (or `make test`).
- Slow extended (~75s: r4_agent, convention, orchestration): `python tests/runner.py --batch 2` (or `make test-extended`).
- Single file: `python -m pytest tests/l1/test_kernel.py -x -q`; keyword: `python -m pytest tests/ -k "kernel" -x -q`.
- Run in the WSL venv: `source .venv/bin/activate` (a Windows-side `python.exe` lacks xdist/mypy deps and is not a valid substitute).
- Plain `pytest` already parallelizes (`-n auto --dist loadfile`); the `-n 0` pins in CI are explicit overrides for infra/L1/L3-root/L5 steps.

## 5. Fix Conventions

- Expected failures return structured dicts (`{"success": False, "error": ...}`); exceptions are for exceptional conditions only.
- No bare `except:` — always `except Exception:` with a real handler (log + structured error).
- Log via module `logger = logging.getLogger(__name__)`, never `print()`.
- Magic values (timeouts, truncation) come from params by name (`LOG_TRUNC_*`, `HASH_TRUNC_*`, `TOOL_*`).
- After fixing, add a regression test; register new singletons in `_RESETS`; keep commits on a `feature/` branch per git-workflow.
