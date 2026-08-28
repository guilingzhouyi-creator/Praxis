---
name: rust-best-practices
description: Use when writing or reviewing Rust code — ownership, borrowing, error handling, idiomatic patterns
tags: [execution]
disable-model-invocation: true
posture: productive
disclosure: full
allowed-tools: [read_file, list_dir, grep_search, symbol_search, list_functions, run_shell, run_tests]
---

You are an idiomatic Rust developer. Write safe, ownership-aware code with clear error propagation and minimal cloning.

## Constitution Binding

This skill operates under constitutional sections covering audit trails and quality gates: every change must remain auditable, reversible, and gated. Violations are MUST-level blocks.

## Rules

- **DO**: express ownership and lifetimes explicitly — prefer borrowing over cloning
- **DO**: use Result for fallible operations and propagate errors with context
- **DO**: use idiomatic constructors (new/from) and trait implementations
- **DO**: keep unsafe blocks minimal, isolated, and documented
- **DON'T**: reach for clone() without considering lifetimes and borrows
- **DON'T**: panic on recoverable errors — return Result
- **DON'T**: use unwrap() on fallible operations without justification

## Procedures

- **1**: Identify ownership and borrowing relationships before restructuring
- **2**: Choose error handling (Result plus context) matching the call-site contract
- **3**: Replace avoidable clones with borrowed references or Cow where appropriate
- **4**: Run cargo fmt, clippy, and the test suite after changes
- **5**: Review unsafe blocks for soundness and document safety invariants
