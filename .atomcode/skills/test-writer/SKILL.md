---
name: test-writer
description: Automatically generate tests following project test conventions, and add coverage for new or untested source files. Use when asked to write tests, add coverage, or increase coverage for a module.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Write, Bash
---

## Overview

Automated test writer for the Praxis codebase. Analyzes source files, identifies uncovered code paths, and generates pytest tests matching the project's conventions.

## When to Use

Invoke via `/test-writer <source_file>` when:
- Adding coverage for a module that lacks tests.
- Filling in uncovered branches or edge cases.
- Asked to increase overall test coverage.

## Workflow

### 1. Analyze Source File

Read the target file at `$ARGUMENTS`. Identify:
- All public classes, functions, and methods.
- Input parameters, return types, and error paths.
- Conditional branches and edge cases.

### 2. Match Project Conventions

Reference existing test files (`tests/test_*.py`) for style patterns:
- `from __future__ import annotations` at top.
- `sys.path.insert(0, ...)` to import from `systems/python-reference-runtime/`.
- Class-based grouping: `class TestFoo:`.
- Plain `assert` statements (no `self.assertEqual`).
- `conftest.py` autouse fixtures handle singleton resets.

### 3. Generate Tests

Cover:
- Normal/positive paths.
- Boundary conditions.
- Error paths and exception handling.
- Edge cases in conditional logic.

### 4. Write Test File

Map source to test path:
- `systems/python-reference-runtime/l1/kernel/foo.py` → `tests/l1/test_foo.py`
- `systems/python-reference-runtime/l2/foo.py` → `tests/l2/test_foo.py`
- `systems/python-reference-runtime/l3/foo.py` → `tests/l3/test_foo.py`
- etc.

If the test file already exists, append new tests rather than overwriting.

### 5. Verify

Run `python -m pytest <test_file> -x -q --tb=short`. If any tests fail, diagnose and fix before reporting completion.
