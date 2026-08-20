# Praxis Multi-Language Migration — run_code / Code Mode (PTC) language backends

> Status: build scaffold active (Python backend shipped; TypeScript protocol
> mirror and Rust contract workspace are in place). Associated design:
> `docs/roadmaps/frontend-kernel-roadmap.md`
> (Rust kernel sink, TS frontend, language-neutral contract).

## 0. Purpose

Python is the current **abstraction base**, not the final language. The
eventual stack is a Rust kernel + TypeScript + Python + HTML + C front-end
family (see the frontend-kernel roadmap). The `run_code` transport (Code
Mode / PTC) must therefore be **language-agnostic by construction** so a
new language is one backend registration — not a framework change.

This document is the conversion path for adding TypeScript and Rust
backends to the Code Mode / PTC presentation layer.

## 1. The backend model (already in place)

`src/l3/tool_system/tool_presentation.py` defines one abstraction the whole
framework depends on:

```
CodeLanguageBackend (ABC)
├── language      → "python" | "typescript" | "rust" | ...
├── file_suffix   → ".py" | ".ts" | ".rs" | ...
├── render_sdk(tools)   → SDK declarations for the model prompt
├── render_usage()      → language-specific usage instructions
└── execute(path, timeout) → run the program (subprocess, hard timeout)
```

Registration: `register_language_backend(backend)` /
`get_language_backend(language)`; the default language is
`CODE_RUN_DEFAULT_LANGUAGE` (config, currently `"python"`). `PythonLanguageBackend`
is registered at import time. `get_renderer()` / `register_renderer()` remain
as backward-compatible aliases.

**The framework never hardcodes a language.** All call sites go through
`get_language_backend()`:

| Call site | Uses |
|---|---|
| `l3/tools/_run_code.py` | backend validation (no backend → graceful reject with available list), `file_suffix`, `execute()` |
| `l3/agent/agent_loop_context.py` | `render_sdk()` + `render_usage()` for system-prompt injection |
| `l3/tool_system/run_code_cache.py` | `language` entry metadata (default from `CODE_RUN_DEFAULT_LANGUAGE`) |
| `config/tools.yaml` | `run_code.language` param description (language-neutral) |

## 2. Adding a TypeScript backend

1. **New file** `src/l3/tool_system/ts_language_backend.py` (or extend
   `tool_presentation.py`):

   ```python
   class TypeScriptLanguageBackend(CodeLanguageBackend):
       language = "typescript"
       file_suffix = ".ts"
       def render_sdk(self, tools): ...   # emit TS bindings (deterministic!)
       def render_usage(self): ...        # TS usage text
       def execute(self, path, timeout):
           from l1.kernel.ports import get_process_port
           return get_process_port().run(f"node {path}", timeout=timeout)
   ```

2. **Register** in `tool_presentation.py` at import time (alongside
   `PythonLanguageBackend`):

   ```python
   register_language_backend(TypeScriptLanguageBackend())
   ```

3. **No framework change is needed** — `_run_code.py`,
   `agent_loop_context.py`, `run_code_cache.py`, and the `run_code` tool
   contract already delegate to the backend. This is the entire point of the
   composite backend design.

4. **Execution runtime**: TypeScript execution requires Node on the host
   (the same constraint as any `ProcessPort`-based tool). Deterministic SDK
   rendering keeps the prompt prefix byte-stable for vendor KV-cache hits.

## 3. Adding a Rust backend

Rust follows the same shape, with two additional considerations tied to the
roadmap's Rust kernel sink (`l1_kernel_rs`):

> **Boundary baseline**: `docs/roadmaps/kernel-boundary-audit.md` (score 42/100)
> defines what `l1_kernel_rs` may carry — mechanism only (sync / event / process /
> allocator / gatechain / constitution + a single invoke-capability gate). Policy
> (skills, prompts, model registry, scheduler strategy) stays in Python/config.
> Re-run the §4 invariant checklist before `execute()` delegates to the Rust
> kernel's process/fs ports.

1. **Backend file**: `rust_language_backend` with `language="rust"`,
   `file_suffix=".rs"`, `render_sdk()` emitting Rust bindings, and
   `execute()` invoking `rustc`/`cargo` (or a precompiled runner) with a
   timeout.
2. **Kernel integration**: when `l1_kernel_rs` ships (per the roadmap's
   scaling-curve gating), the `execute()` path may be delegated to the Rust
   kernel's process/fs ports — the backend seam
   isolates this swap; port abstractions keep callers unchanged.
3. **Constants**: reuse `params/` + `config/praxis.yaml` as the single
   source of truth (no duplicated decision formulas), mirroring the roadmap
   rule for `l1_kernel_rs`.

## 4. What must stay language-neutral

| Rule | Rationale |
|---|---|
| Never compare `language != "python"` in framework code | A new backend must not require touching the rejection logic |
| `execute()` returns `ProcessResult` (`returncode`/`stdout`/`stderr`/`timed_out`/`error_kind`) | Callers (`_run_code.py`) are contract-bound, not interpreter-bound; adapter errors are distinct from child exits |
| SDK rendering stays deterministic (sorted tools, fixed ordering) | Byte-stable prompt prefix → vendor KV-cache hits |
| Usage text comes from `backend.render_usage()` (prompt override only as a global fallback) | Language-specific instructions travel with the backend |
| Cache entries carry `language` from the backend/config default | Future cross-language cache separation keys on this field |

## 4.1 Automation and benchmark perimeter

The declarative automation runner and performance harness are host-side build
tools, not Code Mode language backends. They must remain outside the TS L2
engine and the Rust kernel mechanism set.

- Execution is bound to the language-neutral `ProcessPort` / `ProcessResult`
  contract, so a Rust process adapter can replace the Python adapter without
  changing `automation.yaml` schema v1 or report consumers.
- Performance reports use a versioned JSON schema. L2 protocol measurements are
  regression evidence only; Rust migration priority still requires the fixed-work
  Amdahl benchmark from `frontend-kernel-roadmap.md`.
- G4 is now implemented: sampler defaults live in
  `config/quality/perf-harness.yaml`, and stable L1 observability, evidence,
  trace, and dependency-graph ports isolate the runner from L3 implementations.
  Boot adapters remain replaceable; standalone automation keeps its local
  fallback behavior.

## 5. Open items / deferred

- `CODE_RUN_DEFAULT_LANGUAGE` stays `"python"` until a second backend ships
  and a deployment actually switches; the value is config, not a hard gate.
- Front-end (HTML / TUI / desktop / web) language-neutrality is owned by the
  frontend-kernel roadmap (L2 shell variants + `/api/v2/*` contract); the
  `presentation` API (`/api/v2/presentation`) and L2 command (`presentation`)
  are the switch surface.
- C-family backend (if ever needed for the kernel layer) follows the same
  `CodeLanguageBackend` shape.

## 6. Acceptance criteria for a new backend

1. `register_language_backend(NewBackend())` → `run_code` accepts the
   language and executes a real program (smoke test).
2. `run_code` with an unregistered language returns a graceful error listing
   available backends (existing behavior, unchanged).
3. `presentation_status()` lists the new language in `languages`.
4. Full gates green: ruff / layer-import / params-compliance / domain tests /
   full baseline; docs updated in the same commit.

## 7. Build scaffold (M0.5)

The language build perimeter is now executable without changing the Python
runtime:

- `packages/protocol-ts/package-lock.json` fixes the TypeScript/Vitest graph;
  `npm ci` is the only clean-install path used by the Makefile and CI.
- `crates/` is a pinned Rust 1.97.1 workspace with `rustfmt` and `clippy`.
  `l1-kernel-rs` exports only a versioned contract descriptor and forbids
  unsafe code.
- `make language-check` runs TS tests/typecheck plus Rust test, format, and
  clippy gates. `.github/workflows/multilang.yml` runs the same gates on
  relevant changes.

This milestone deliberately does not add FFI, a Rust process adapter, a TS
session authority, or a second scheduler. Those remain M1–M4 work and require
the port, protocol, and performance evidence gates described above.
