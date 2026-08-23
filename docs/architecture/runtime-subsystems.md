# Runtime subsystems (unified view)

The agent runtime side of Praxis that the layer docs do not fully own:
error bus, agent loop entities, boot, search, LLM workers, resource
buffers, and config discovery. 64 files / ~11,000 lines across
`l3/error_bus`, `l3/agent`, `l3/agent_terminal`, `l3/boot`,
`l3/resource_buffer`, `l3/config`, `l4/search`, `l4/llm_worker`.

## Responsibility boundary

- Cross-cutting runtime services consumed by every layer, wired at boot.
- No HTTP/API surface of their own (except search/vault adapters exposed
  via `l4-bridge.md`).

## Subsystems

| Subsystem | Files | Role |
|-----------|-------|------|
| `l3/error_bus/` | 6 | Unified `trace_id`: one id flows request → agent → tool → error (`get_trace_id`/`set_trace_id`/`trace_scope`); `capture()` error records |
| `l3/agent/` | 38 | AgentLoop entity (per-session loop, tool wrapping, prompt assembly `agent_loop_context`), skill/identity/card injection, R4 skill retrieval |
| `l3/agent_terminal/` | 3 | Terminal binding: territory + role + agent identity → concrete executor (filesystem/tool access) |
| `l3/boot/` | 6 | 7-step bootstrap (`boot.py`), factory reset / singleton reset / disk wipe (`lifecycle.py`), wiring adapters → ports (`wiring.py`) |
| `l3/resource_buffer/` | 4 | Buffer manager for bounded resource pools (executors, tokens) |
| `packages/protocol-ts/` | 30+ | L2 TS engine: protocol v1 wire contract, session multiplexer, bridge client, transports (stdio/http/ws/ssh), middleware, output guard |
| `l3/config/` | 14 | `ConfigDiscovery` — auto-loads `config/discovery/*.yaml` at boot (departments, diff languages, etc.) |
| `l4/search/` | 4 | FTS5 + AST symbol search (`SymbolSearch.symbols_in_file`, `search_engine.py`) used by diff review |
| `l4/llm_worker/` | 5 | Background LLM workers (async generation outside request paths) |

## Error bus (unified trace)

- `trace_scope` context manager sets the current `trace_id` for the
  duration of a request; every downstream capture/error inherits it.
- New code paths propagate the existing id — never mint a fresh one.
- `capture()` emits structured error records (code/component/exc) into
  the RecordCenter + event bus; see `cross-cutting.md` §events.

## Agent loop entities

- `AgentLoop` is a per-session entity: one loop per task, carrying
  `agent_id` / `role` / `cell_id` / `task`; prompt assembly in
  `agent_loop_context.py` injects constitution summary, identity binding,
  card-domain fragment, HTN-C identity hit, per-Cell Agents handbook
  (`Cell-{cell_id}-Agents.md`), skills and lean cases (bounded budget).
- Cell agents are **peer entities** — identity is driven by HTN-C task
  dispatch (`match_identity`), never a static role.

## Boot (7-step)

`boot.py` orchestrates: kernel wiring → ports → config discovery →
memory init → cell creation → agents → watchdog. `lifecycle.py` owns
factory reset / singleton reset / disk wipe (operator-gated). Every
boot-registered module is listed in `tests/conftest.py` `_RESETS`.

## Contract surface

- `l3/error_bus` API: `get_trace_id` / `set_trace_id` / `trace_scope` /
  `capture`
- `l4/search`: `SymbolSearch.symbols_in_file(path)` → symbol list
- `l3/boot`: `boot.boot()` / `lifecycle.factory_reset()`
- Ports: none dedicated (in-process services); adapters wired via
  `register_port()`/`get_port()` in `l3/boot/wiring.py`

> Counts refreshed 2026-08-22 against `feature/l3-normalize`. Full per-directory
> map: see `l3-module-map.md`.
