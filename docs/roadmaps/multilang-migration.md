# Praxis Multi-Language Migration — run_code / Code Mode (PTC) language backends

> Status: planning (Python backend shipped; TypeScript / Rust backends are
> slots). Associated design: `docs/roadmaps/frontend-kernel-roadmap.md`
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
           from l1.kernel.platform import run_shell
           return run_shell(f"node {path}", timeout=timeout)
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
   (the same constraint as any `run_shell`-based tool). Deterministic SDK
   rendering keeps the prompt prefix byte-stable for vendor KV-cache hits.

## 3. Adding a Rust backend

Rust follows the same shape, with two additional considerations tied to the
roadmap's Rust kernel sink (`l1_kernel_rs`):

1. **Backend file**: `rust_language_backend` with `language="rust"`,
   `file_suffix=".rs"`, `render_sdk()` emitting Rust bindings, and
   `execute()` invoking `rustc`/`cargo` (or a precompiled runner) with a
   timeout.
2. **Kernel integration**: when `l1_kernel_rs` ships (per the roadmap's
   scaling-curve gating), the `execute()` path may be delegated to the Rust
   kernel's process/fs ports instead of `run_shell` — the backend seam
   isolates this swap; port abstractions keep callers unchanged.
3. **Constants**: reuse `params/` + `config/praxis.yaml` as the single
   source of truth (no duplicated decision formulas), mirroring the roadmap
   rule for `l1_kernel_rs`.

## 4. What must stay language-neutral

| Rule | Rationale |
|---|---|
| Never compare `language != "python"` in framework code | A new backend must not require touching the rejection logic |
| `execute()` returns a `run_shell`-like object (`returncode/stdout/stderr`) | Callers (`_run_code.py`) are contract-bound, not interpreter-bound |
| SDK rendering stays deterministic (sorted tools, fixed ordering) | Byte-stable prompt prefix → vendor KV-cache hits |
| Usage text comes from `backend.render_usage()` (prompt override only as a global fallback) | Language-specific instructions travel with the backend |
| Cache entries carry `language` from the backend/config default | Future cross-language cache separation keys on this field |

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
