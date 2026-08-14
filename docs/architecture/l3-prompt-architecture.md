# L3 — Unified System-Prompt Architecture (libraries + versioning + monitor)

Layered system-prompt management: a Cell-domain shared library (two-layer)
and a global shared library (sub-libraries) replace the flat, scattered
prompt registry, with version tracking and a bypass quality monitor. All
text is config-driven and system-managed (user edits forbidden); every
feature is operator-gated via API + L2 Shell.

## Layers

| Layer | Key prefix | Scope | Module |
|-------|-----------|-------|--------|
| Cell shared base | `cell.shared.*` | one Cell's 3 Peer Agent sessions (upper layer) | `l3/agent/prompt_library.py` |
| Cell dynamic docs | `Agent-{cell_id}.md` | per-Cell dynamic prompt, auto-hit by context pressure (lower layer) | `l3/agent/prompt_library.py` |
| Global base + sub-libs | `global.*` / `global.<sub>.*` | cross-Cell shared base + security / performance / extension sub-libraries | `l3/agent/global_prompt_library.py` |

## Injection order (agent_loop_context)

`system` → constitution/identity/verification fragments → per-Cell Agents
handbook (`Cell-{cell_id}-Agents.md`) → **Cell prompt library**
(`resolve_cell_prompt(cell_id, pressure)`: shared base always, dynamic doc
appended when `pressure >= PROMPT_LIBRARY_PRESSURE_HIGH`) → **global prompt
library** (`resolve_global_prompt(load, domain)`: performance under high
load, security on security domains, extension baseline) → tool
presentation (Code Mode SDK/usage).

Pressure/load sources: `_pre_send_compression_guard` measures
`ratio = est_total / ctx_window` and exposes it as `_context_pressure` and
`_system_load`, so the dynamic auto-hit engages under real load.

## Config & switches

- Sub-library text: `config/prompts/<sub>.md` (lazy-loaded once, layered
  key `global.<sub>` fallback); Cell base falls back to `cell.shared.base`.
- Operator switches (API + L2 Shell): `prompt-library` (cell + global,
  default ON), `prompt-version` (default ON), `prompt-monitor` (default
  OFF = production; ON = engineering/debug).
- **Read-only**: the libraries are system-managed — write functions
  (`set_shared_base`, `set_dynamic_doc`, `register_sub_library`) reject any
  non-`system` source.

## Versioning (P1-⑤)

`prompts.py` records a revision per prompt key on every override load
(`load_prompt_overrides` → `_record_version`), keeps a text snapshot per
(key, version), and exposes `prompt_versions()` / `rollback_prompt(key,
version)` (rollback itself becomes a new revision). API: `GET
/api/v2/memory/prompt-version` + `POST .../rollback`; L2 `/memory
prompt-version [snapshot|rollback=key@ver]`.

## Bypass monitor (P1-⑥)

`l3/agent/prompt_monitor.py` quantifies per-key usage frequency and
success/failure rates (`record_prompt_usage` via an L1 hook installed on
enable, `record_prompt_outcome`), aggregates `prompt_monitor_stats()`, and
correlates with the reference channel via `prompt_metrics` events
(`emit_prompt_metrics`). `get_prompt_monitored` triggers the hooks — the
run_code usage getter uses it in production paths. Default OFF
(production); ON = engineering/debug mode. API: `GET/PUT
/api/v2/memory/prompt-monitor` + `POST .../emit`; L2 `/memory
prompt-monitor [on|off|stats|emit]`.

## Contract surface

- `GET /api/v2/memory/prompt-library` / `PUT` — library switches
- `GET /api/v2/memory/prompt-version` / `POST .../rollback` — versioning
- `GET /api/v2/memory/prompt-monitor` / `PUT` / `POST .../emit` — monitor
- L2: `/memory prompt-library`, `/memory prompt-version`,
  `/memory prompt-monitor`
- Params: `PROMPT_LIBRARY_*`, `GLOBAL_PROMPT_*`, `PROMPT_VERSIONING_*`,
  `PROMPT_MONITOR_*` (`params/system.py`)
