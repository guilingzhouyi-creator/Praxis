---
name: code-reviewer
description: Automated code quality review for NOMOS Praxis. Runs in parallel to review kernel/services code against project conventions.
allowed-tools: Read, Grep, Glob, Bash
---

## Overview

Code quality reviewer for the Praxis codebase. Triggered on code changes to review architecture, code quality, thread safety, error handling, and test coverage.

## Workflow

### 1. Scan Changed Files
Identify files in the change set. Prioritize kernel (`src/l1/kernel/`), cell (`src/l3/`), bridge (`src/l4/`), and shell (`src/l2/`) layers.

### 2. Architecture & Design Review
- Verify syscall patterns are followed consistently (all kernel ops through `syscall()`).
- Check service boundary is respected (L1-L5 layer separation per import rules).
- Detect circular dependencies between modules.
- Verify singleton accessors (`get_*()`) are used correctly.

### 3. Code Quality Review
- Check naming conventions: snake_case functions, PascalCase classes, UPPER_SNAKE_CASE constants.
- Verify full type hints on all public functions.
- Confirm no mutable default arguments.
- Check no bare `except:` clauses.
- Verify magic numbers are defined in `params/` rather than hardcoded.
- Confirm double quotes for strings, line-length ≤ 120.
- Confirm comments/docstrings are in English (no CJK residue outside i18n data).

### 4. Thread Safety Review
- Verify shared resources protected with `threading.RLock()`.
- Confirm `with lock:` context manager used consistently.
- Identify potential deadlocks or race conditions.

### 5. Error Handling Review
- Verify structured dict returns (`{"success": bool, "error": str}`) for expected failures.
- Confirm exceptions raised only for truly exceptional conditions.
- Check `logger.error()` used instead of `print()`.

### 6. Testing Review
- Verify new code has corresponding tests in `tests/`.
- Confirm tests use pytest patterns.
- Check that new singleton services have reset functions registered in `tests/conftest.py`.
- Check `tests/infra/test_layer_imports.py` allowlist updated for any new cross-layer imports.

### 7. Gate & Compliance Review
- **CompletionJudge alignment**: confirm the change set satisfies the 11 dimensions of `verify-completion.sh` (tests / coverage ≥60 / net delta / doc-stats / lint+mypy / CVEs / complexity / import cycles / singleton drift / CHANGELOG / doc-index). Flag anything that would return INCOMPLETE.
- **Mainline net-delta gate**: estimate the change's net code delta (added − deleted, after comment stripping) — small changes (< 1000 net) must accumulate on the worktree branch; never suggest `MERGE_GATE_SKIP=1` (waivers are the human's decision).
- **Doc sync**: architecture-level changes (new module/service, changed contract, renamed subsystem, new params domain) MUST carry their `docs/architecture/` update in the same commit; generated numbers refreshed via `make doc-stats`, never hand-edited.
- **Security posture / harness changes**: any posture (`security_mode.py`) or harness (`harness.py`) change MUST record evidence (`record_evidence`); a downgrade (e.g. `minimal` harness) must never be hardcoded silently.

## Checklist

- [ ] Architecture follows kernel syscall / service layer pattern
- [ ] No circular dependencies introduced
- [ ] Layer import rules respected (L5→L4/L3→L2→L1 only); allowlist updated
- [ ] Naming conventions followed (snake_case, PascalCase, UPPER_SNAKE_CASE)
- [ ] Full type hints on all public functions
- [ ] Thread safety: reentrant locks on shared state, no mutable defaults
- [ ] Structured error returns, not bare exceptions
- [ ] No hardcoded magic numbers — use params/
- [ ] Double quotes, line-length ≤ 120
- [ ] Corresponding tests exist
- [ ] Logger used instead of print
- [ ] Module docstring present
- [ ] No CJK in comments/docstrings
- [ ] CompletionJudge 11 dimensions satisfiable; net-delta gate not evaded
- [ ] Architecture doc updated in the same commit; doc-stats regenerated
