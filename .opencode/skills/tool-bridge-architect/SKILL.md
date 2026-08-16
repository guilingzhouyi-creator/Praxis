---
name: tool-bridge-architect
description: Use when writing or modifying Praxis tool system or bridge layer code — tool pipeline, ToolSpec registration, ring/danger posture, tools.yaml, sandbox structured diff system, API gateway routes, MCP servers, or LLM provider config.
---

## Overview

Architecture guide for the tool execution system (`src/l3/tool_system/`) and the L4 bridge (`src/l4/`: API gateway, LLM engine, sandbox, MCP, search, LSP, vault). Covers both how tools execute and how the outside world reaches the cell.

## Tool System

- **Pipeline**: `tool_pipeline.py` — 9-step execution pipeline (`ToolPipeline.execute`, `get_pipeline()`/`reset_pipeline()`). Gate traces per phase on the hot path; keep step tracing toggleable.
- **Registration**: `ToolSpec` (`tool_spec.py`, `tool()` decorator, `execute_tool_spec`), registered via `register()`/`register_plugin()` (`tool_registry.py`) with ring/danger/parameters defined in `config/tools.yaml` (72 tools by ring layer). Middleware hooks: `register_middleware(hook_type, name, fn)`.
- **Muting**: `mute_tool`/`mute_category`/`mute_plugin`/`mute_ring` in `tool_registry.py` — respect muted state in any new execution path.
- **Security posture**: `security_mode.py` (posture get/set with `confirmed`), `security_evidence.py` (evidence rows, `record_evidence`, bounded raw), `harness.py` (harness mode), `auto_test.py` (test feedback loop: `push_feedback`/`pop_feedback`/`maybe_trigger`).
- **Config**: `tool_config.py` resolves handler paths + param specs from YAML. Tool timeouts use `TOOL_*` constants from `src/l1/kernel/params/tool.py` (e.g. `TOOL_PACKAGE_MANAGER_TIMEOUT`, `TOOL_PIP_INSTALL_TIMEOUT`) — never inline numbers.
- **Platform**: use `l1.kernel.platform` abstractions (`grep_cmd()`, `run_shell()`, `IS_*` flags) for OS-specific ops; never self-implement platform subprocess calls.

## Bridge Layer (L4)

- **API gateway**: routes under `/api/v2/` in `api_routes.py`; the manifest (`api_endpoints.py`) is the single source of truth — register via `register_endpoint()`/`register_domain()`/`register_group()`, never hand-edit `API_ROUTES`. Path rules: kebab-case, `{param}` placeholders mirroring handler kwargs, no trailing-slash params. Run `python -m l4.api.api_endpoints` before pushing API changes; breaking changes require a new version segment (`/api/v3/`).
- **Sandbox / structured diff**: every sandbox entry records per-hunk attribution (`agent_id`, `tool_name`, `task_id`, `modified_at` ISO 8601); entries keyed `path::agent_id` so parallel agents edit the same file independently and cross-review sees all entries. Summary cache L1→L3 → persistent `.praxis/sandbox_state.json` (in `data_dir`). Diff views: `agent`, `human`, `summary`, `colored` (colors via `config/praxis.yaml` `diff.colors`; `POST /api/v2/diff/colors` get/set/reset).
- **LLM engine**: providers pluggable; default `ollama`/`codellama:7b` at `localhost:11434`, overridable via `config/praxis.yaml` or env (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_URL`). Provider creds live in the vault, never in code.
- **LLM failover** (`llm_retry.py`): after `LLM_FAILOVER_THRESHOLD` (3) consecutive failures on the primary provider, the next call rebuilds from `ModelRegistry.get_fallback` — SAME model-spec semantics (role/executor kept; provider/endpoint/credential swapped) — and replays once. Success resets the counter; `LLM_FAILOVER_COOLDOWN` (300s) since last switch prevents thrashing; `LLM_FAILOVER_ENABLED` is the master switch (default on); no fallback keeps the primary and returns the error payload (see the **llm-engine** skill for the full contract).
- **MCP**: server definitions under `config/praxis.yaml` `mcp:`; new servers follow the local/remote distinction and load at boot.
- **Search/LSP/vault**: `search.py`, `lsp.py`, `vault.py` — vault access is identity-checked; keep LLM provider config out of logs.

## Conventions

- Tool execution must return structured dicts (`{"success": bool, "error": str, ...}`); expected failures are values, not exceptions.
- All timeouts/limits are params constants; trace_id flows request → agent → tool → error via error_bus (`get_trace_id`/`set_trace_id`/`trace_scope`) — never mint new ids.
- New bridge services need reset functions registered in `tests/conftest.py` `_RESETS`.

## Tests

- `python -m pytest tests/ -k "tool or sandbox or api or mcp" -x -q`; endpoint manifest test in the L4/API area.
