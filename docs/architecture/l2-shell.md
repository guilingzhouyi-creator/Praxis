# L2 — Shell Family Layer

Human interface: a family of shells (dialect adapters) over one shared
command engine — 51 YAML commands + 65 `_cmd_*` handler functions (17 code-only),
i18n, completion, agent selection, per-session state.

## Shell family model

L2 follows the Linux model: one stable engine contract, many shells that
translate frontend dialects into it.  A shell turns input lines into
render-ready dict results; the engine (`l2_shell` dispatch) never changes
when a new frontend appears — a new frontend registers a new shell.

```
frontends (CLI / TUI / desktop / API)       — L5 / L4
        │  render-ready dicts
        ▼
shells/    Shell         (dialect adapter: name, run(text, session) → dict,
        │                  create_session)              — shells/base.py
        │  ShellFamily   (register/get/list/bind/resolve, config-loaded,
        │                  revision-based)              — shells/family.py
        │  ShellSession  (per-session mode/cell/agent state) — shells/session.py
        ▼
l2_shell/  shared engine: dispatch (| pipeline, / commands, Direct mode, L3A)
```

## Core modules

| Module | Role |
|--------|------|
| `shells/base.py` | `Shell` ABC — dialect contract: `run(text, session) -> dict`, `create_session()` |
| `shells/family.py` | `ShellFamily` registry + frontend bindings + default dialect; instantiated from config |
| `shells/session.py` | `ShellSession` — per-session mode (L3A/Direct), cell, agent, session id |
| `shells/terminal.py` | `TerminalShell` dialect: `!intent` → L3A, `$cmd` → system, `/cmd` → engine, tool calls |
| `l2_shell/` | Shared command engine: `dispatch`, commands, output guard, settings/model commands |
| `commands/` | Per-domain command handlers (memory, settings, model, …) returning dicts |
| `i18n.py` | Localization (en/zh-CN/ja/ko), cached adapter |
| `shell_completer.py` | Tab completion + aliases (revision-based cache) |
| `selector.py` | Agent selector (locked index) |

## Shell family lifecycle

- Members are declared in `config/discovery/shells.yaml` (module + class
  per member); the boot step `init_shells` (L3) instantiates them into the
  family from the three-layer config: params defaults ← discovery YAML ←
  praxis.yaml `shells:` deployment overrides.
- `ShellFamily` is revision-based like `CommandRegistry`; `resolve(frontend)`
  falls back to the configured default dialect.  No shell is hardcoded —
  adding a frontend means declaring a shell in YAML.
- `l2_shell/state.py` is a thin accessor over the ShellFamily default
  shell's session: `get_state()` / `reset_state()` delegate to
  `get_family().default()` (with a stable fallback while the family is
  empty, e.g. early boot / isolated tests).  It is NOT a second
  process-global state source — new code passes a `ShellSession`
  explicitly to `dispatch(text, session=None)`; legacy callers (L4 API
  handlers, command handlers, completer) read the default shell's session
  through the accessor.

## Interaction model

```
line ──┬─ !<intent>            → L3A direct session (cardwrite path)
       ├─ !<intent>@cell/agent → routed direct session
       ├─ $ <command>          → raw system command (ProcessPort.run)
       ├─ <tool> <args>        → tool execution (aliases: rf→read_file)
       └─ /command             → engine dispatch (dict results)
```

## Bottom-layer boundary (Phase 5)

How L2 touches the OS boundary, and where a future Rust sink (roadmap
§4.3, port-adapter replacement) can hook in without changing the engine:

| Boundary | Current path | Port abstraction | Rust-sink candidate |
|----------|--------------|------------------|---------------------|
| `$ <command>` system exec | `get_process_port().run` (value result, cross-platform) | `ProcessPort` (`run` / `run_args`, explicit `ProcessOptions`) | ✅ adapter replacement, including pre-boot stdlib fallback |
| File tools (read/write/tree) | `l3.tool_system` → `l3.services.fs_adapter` | `FilesystemPort` (`l1.kernel.ports`) | ✅ adapter swap, contract stable |
| Worker / pool execution | `l3.boot.wiring` registers `"worker"` | `WorkerPort` (`l1.kernel.ports`) | ✅ adapter swap |
| Terminal dialing (interactive) | `l2.shell_session` live `Popen` + `shell_completer` | Python-only lifecycle | — (not an FFI-clean one-shot port); module kept for tests only, zero production callers (`TerminalManager`), candidate for removal with the TS engine cutover |

Rule: the L2 engine only calls the port/platform abstractions above —
never raw `os`/`subprocess` — so swapping the adapter (Python → Rust) is
invisible to `dispatch` and every shell dialect.

## Contract surfaces

- Shell contract: `name` + `run(text, session) -> dict` + `create_session()`
- Engine contract: `dispatch(text, session=None) -> dict` (`|` pipeline,
  `/` commands, Direct mode, L3A intent)
- L3A direct session routing: `_handle_direct` → `intent_parse` → card
- Tool execution via the single gated capability seam
  (`l1.kernel.capability.invoke_capability`, wired at boot to the L3 ToolPipeline adapter)
- Event emission: shell state changes / human corrections
  (`reference_channel.human_correction` — a profile collector source)
- HTTP contract (language-agnostic, see `l5-user.md`):
  - `POST /api/v2/shell` → `dispatch(text, session)` (one input line)
  - `GET  /api/v2/shell/autocomplete` → partial-line suggestions
  - `GET  /api/v2/shell/commands` → command registry list (category filter)
  Handlers live in `l4/api_handlers/api_handlers_agent.py`; wired by
  `frontend-kernel-roadmap.md` Phase 1–3 (M1).

## Key points

- **L3A/Direct mode** lives per-session on `ShellSession` (reset per test
  via conftest `_RESETS`: `l2.shells.family`, `l2.l2_shell.state`).
- Handlers are the frontend contract: CLI/TUI/API render the same
  dict-returning surfaces (see `l5-user.md`).
- `TerminalShell` keeps the legacy `direct_session` / `start_repl` entry
  points as thin wrappers over the class.
