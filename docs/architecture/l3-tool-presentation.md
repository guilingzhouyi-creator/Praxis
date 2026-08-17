# L3 — Tool Presentation (Code Mode / PTC)

Code Mode (PTC) presentation layer: how the tool registry presents tools to
the model, and the `run_code` transport for programmatic tool composition.

## Summary

`tool_presentation` adds a third tool-presentation mode (`code` / `both`) on
top of the default `native` function-calling schemas. Under `code` the model
writes a Python program against a generated SDK and submits it via the
reserved `run_code` tool: multi-step tool calls (loops, branches, fan-out)
run in one sandboxed execution, only the program's printed output and return
value re-enter the model context (token savings), while every tool call the
program makes is still recorded on the tool audit chain. Per-Cell program
reuse (tiered-cache + tf-idf similarity + incremental patch + TTL) avoids
re-entering and re-executing near-identical programs.

## Inventory

| Module | Role |
|---|---|
| `l3/tool_system/tool_presentation.py` | Presentation-mode runtime switch (`native`/`code`/`both`), language-agnostic `CodeLanguageBackend` composite (SDK render / usage / file suffix / execute), Python backend, per-Cell program cache dir |
| `l3/tool_system/run_code_cache.py` | Per-Cell program cache: tiered-cache storage, tf-idf similarity, TTL renewal, incremental-patch evidence, reclamation |
| `l3/tools/_run_code.py` | `run_code` tool handler: validate → cache-hit check → in-process execution with injected bindings (Python) / subprocess (other backends) |
| `l1/kernel/params/tool.py` | `TOOL_PRESENTATION_*` / `CODE_RUN_*` constants (modes, limits, cache TTL/floor) |
| `l3/agent/prompts.py` (WS5.3; kernel keeps a shim) | `agent_loop.run_code_usage` — Code Mode usage instructions |
| `l3/agent/agent_loop_context.py` | Model-facing tool filtering (code-only) + SDK/usage injection |

## Presentation modes

| Mode | Model-facing tools | SDK section | notes |
|---|---|---|---|
| `native` (default) | all registered tools | none | unchanged behavior; `run_code` hidden |
| `code` | only `run_code` | rendered | other tool names resolve to UNKNOWN_TOOL |
| `both` | all tools + `run_code` | rendered | native schemas and transport together |

Switch at runtime via `set_presentation_mode()` (evidence recorded on the
ambient chain); config key `tool_presentation_mode` resolves
params → discovery → praxis.yaml.

## run_code lifecycle

```text
submit program → validate (size/language) → per-Cell cache similarity hit?
   hit  → renew TTL + record incremental patch → return cached result (no exec)
   miss → write to per-Cell cache area → in-process exec (Python) with
          injected tool bindings / subprocess (other backends) →
          return stdout/exit → write back successful result to cache
```

- **Efficiency**: only program stdout/return value re-enter the model
  context; intermediate tool results do not (unlike native step-by-step).
- **Traceability**: every tool call the program makes passes the pipeline
  with `_parent_call_id` linked to the `run_code` call, so the ToolChain
  fingerprint tree, ledger, and evidence chain record it.
- **Binding wiring**: Python programs run in-process with `_praxis_call`
  injected — each generated SDK binding (`read_file(...)`, …) executes the
  REAL tool through the pipeline (not a stub), so programmatic composition
  actually composes tool executions. Timeout uses a worker thread (not
  SIGALRM — `signal.signal` only works in the main thread, and the pipeline
  runs tools on a ThreadPoolExecutor).
- **Reuse**: `run_code_cache.similar()` (tf-idf cosine, floor 0.35) finds a
  near-identical cached program; the caller then supplies only an
  incremental patch (diff recorded as `run_code_cache/incremental_patch`
  evidence). Successful executions write back program + result to the cache
  (write-back closes the loop — the cache grows organically).
- **Stable prefix**: system + usage + SDK are assembled as a byte-stable
  prompt prefix (`assemble_code_prompt`) for vendor KV-cache hits;
  the incremental suffix (program/patch/results) is appended after it.
- **Reclaim**: entries expire by TTL (`CODE_RUN_CACHE_TTL`, 900s); explicit
  `reclaim()` sweep at Cell teardown.

## Contracts

- `run_code` tool params: `program` (required str), `language` (default
  "python"), `cell_id` (optional). Registered under `layer_3/system` in
  `config/tools.yaml` (DANGER-3 posture, pipeline gates apply).
- `CodeLanguageBackend` composite: `language` + `file_suffix` properties,
  `render_sdk(tools)` + `render_usage()` for the prompt, and `execute(path,
  timeout)` for execution. Python ships as the first backend; TypeScript /
  Rust slots are reserved (see
  `docs/roadmaps/multilang-migration.md` for the conversion path). The
  framework only calls `get_language_backend()` — it never hardcodes a
  language.
- Renderer output is deterministic (sorted, byte-stable) so the SDK section
  forms a stable prompt prefix for vendor KV-cache hits
  (DeepSeek/OpenAI `prompt_cache_retention`, Anthropic `cache_breakpoints`).
