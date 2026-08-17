# L3 — Unified System-Prompt Architecture (libraries + versioning + monitor)

Layered system-prompt management: a Cell-domain shared library (two-layer)
and a global shared library (sub-libraries) replace the flat, scattered
prompt registry, with version tracking and a bypass quality monitor. The
baseline text is config-driven and system-managed (ordinary user edits are
forbidden); every feature is operator-gated via API + L2 Shell. Engineering prompt inspection
and editing is a separate, marker-gated control plane and is never enabled by
ordinary production traffic.

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
  OFF = production; ON = engineering/debug). The engineering-debug manager
  owns the monitor transition, so a direct enable request is rejected unless
  the effective mode is engineering.
- **Read-only**: the libraries are system-managed — write functions
  (`set_shared_base`, `set_dynamic_doc`, `register_sub_library`) reject any
  non-`system` source.

## Engineering debug integration (3.5)

`src/l3/tool_system/engineering_debug.py` is the single authority for the
engineering/debug state. The requested mode is `auto`, `on`, or `off`; the
effective mode is still production unless the configured marker is present:

| Rule | Effective result |
|------|------------------|
| `mode: auto` + no marker | Production (default) |
| `mode: auto` + regular marker file | Engineering |
| `mode: on` + no marker | Rejected/production (the marker is a hard gate) |
| `mode: off` | Production (fail closed, even when a marker exists) |

The default marker is `.praxis/debug_mode.flag`, resolved relative to the
deployment root. A symlink or non-regular path does not satisfy the gate.
The marker is rechecked on a bounded interval (`ENGINEERING_DEBUG_MARKER_RECHECK_INTERVAL`),
so normal prompt reads do not perform an unbounded filesystem walk.

An effective-mode transition applies the linked observability side channels
once and emits `engineering_debug_mode_changed` to EventBus,
ReferenceChannel, and StatsCenter. Engineering mode may enable verbose root
logging and the prompt monitor. Production mode restores the configured log
level, disables the monitor, and does not expose engineering prompt overlays.
Every prompt overlay is persisted under the `engineering_debug.prompt_overrides.*`
runtime namespace, versioned by `l3.agent.prompts` (WS5.3 moved it out of the kernel; the kernel keeps a compat shim), and can be rolled back by
version. Overlay writes require a developer role or ring-3 clearance and are
bounded by `ENGINEERING_DEBUG_PROMPT_MAX_CHARS`; disabling engineering mode
restores the built-in/deployment prompt source.

Input monitoring is a separate, opt-in side channel. It reports only aggregate
keyboard/pointer activity (`active`, `idle`, or `unknown`) through
`InputActivityPort`; key values, pointer coordinates, and raw event streams are
never collected. The provider starts only when both engineering mode and
`engineering_debug.input.enabled` are true.

### Control surface

| Surface | Contract |
|---------|----------|
| API | `GET/PUT /api/v2/engineering-debug` — status and requested mode |
| API | `GET/PUT /api/v2/engineering-debug/prompts` — inspect or set one overlay |
| API | `POST /api/v2/engineering-debug/prompts/rollback` — restore a version |
| API | `GET/PUT /api/v2/engineering-debug/input` — aggregate input status/switch |
| L2 | `/debug-mode status\|auto\|on\|off\|reset` |
| L2 | `/debug-input status\|on\|off` |

All mutating API and shell calls carry an explicit developer identity (or
ring >= 3). The marker gate is independent of this identity gate: a permitted
operator cannot bypass a missing marker.

### Performance and Rust-sink boundary

The debug manager caches marker resolution and applies logging/monitor/input
effects only when the effective state or relevant setting changes. Prompt
version snapshots are bounded by the configured text limit and remain a
side-channel operation; the main agent prompt path is unchanged on errors.
The L1 `InputActivityPort` and `InputActivitySnapshot` are primitive-only
contracts, so a native keyboard/pointer provider can be implemented in Rust
without changing L3 policy or API contracts. The default no-op provider keeps
unsupported platforms and production deployments inert.

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
- Engineering debug API: `GET/PUT /api/v2/engineering-debug`,
  `GET/PUT /api/v2/engineering-debug/prompts`,
  `POST /api/v2/engineering-debug/prompts/rollback`, and
  `GET/PUT /api/v2/engineering-debug/input`
- L2 engineering controls: `/debug-mode` and `/debug-input`
- Params: `PROMPT_LIBRARY_*`, `GLOBAL_PROMPT_*`, `PROMPT_VERSIONING_*`,
  `PROMPT_MONITOR_*`, and `ENGINEERING_DEBUG_*` (`params/system.py`)
