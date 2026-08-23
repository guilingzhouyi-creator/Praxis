# L5 — User Layer

Entry points and user-facing contract. 2 files / ~600 lines:
`src/main.py` (entry + REPL) and `src/l5/cli.py` (command handlers).

## CLI entry (`src/main.py`)

`main.py` inserts `src/` on `sys.path` and dispatches to the handler table
imported from `l5.cli.COMMANDS`:

```python
python src/main.py boot | health | ps | card <intent> [domain] |
                     card-list | card-submit <intent> | card-cancel <card_id> |
                     tools [agent_id] | audit [agent_id] | chain <call_id> |
                     interrupts | devices | status | sys [path] | dev [path] |
                     setting [key [value]] | shutdown | backup [tag] |
                     backups | restore <backup-name> | restart
```

- `python src/main.py -h` prints the module docstring (usage).
- With no argument, `main.py` enters the **REPL** (`repl()`): reads
  `praxis> ` lines, splits on whitespace, resolves `COMMANDS`, and prints
  `Unknown: ...` for unknown commands. `exit`/`quit`/`q` runs
  `shutdown_to_memories()` before leaving; `help` lists command names.
- Every handler returns a dict (the machine contract); printing is a
  per-command side effect. A TUI/desktop can call the same handlers and
  render the dicts — see "Interaction layers" below.

## Command reference (`src/l5/cli.py`)

`COMMANDS` maps 21 names to handlers (last one is a lambda composing
`shutdown` then `boot`). All handlers return a dict; `args` is the
remaining argv list.

| Command | Handler | Args | Behavior / return |
|---|---|---|---|
| `boot` | `cmd_boot` | — | Boot kernel + Cell; prefers the previous boot snapshot via `l3.memory.memory_init.init_from_memories()`, falls back to `TERRITORY_PATHS`; `wire_kernel_os()` + `register_boot_handler(l3_boot)`; starts watchdog on success. Prints boot elapsed/cell/agents. Returns the `osys.boot()` result dict. |
| `health` | `cmd_health` | — | Run `l1.kernel.health()` self-test; prints per-module `[status] name elapsed_ms`. Returns `{status, module_count, modules}`. |
| `ps` | `cmd_ps` | — | List kernel processes from `l1.kernel.process.get_table()`. Returns `{processes: [...]}`. |
| `card` | `cmd_card` | `<intent> [domain]` | Dispatch a card via `l3.cell.get_cell("shell-cell", [domain]).execute_card(intent)`; prints step pass/fail table. Returns the full card result (incl. `steps`). |
| `card-list` | `cmd_card_list` | — | Recent cards from `l3.card.card_registry.get_registry().list(state=None)` (first 20 printed). Returns `{cards}`. |
| `card-submit` | `cmd_card_submit` | `<intent>` | `registry.submit(intent, ".")`; returns `{success, card_id}`. |
| `card-cancel` | `cmd_card_cancel` | `<card_id>` | `registry.cancel(card_id)`; returns `{success}`. |
| `tools` | `cmd_tools` | `[agent_id]` | Without arg lists terminals that own tools; with arg lists one terminal's tools (`ring`, `danger`, truncated description). Returns `{tools, agent}` or `{terminals}`. |
| `audit` | `cmd_audit` | `[agent_id]` | Syscall audit log via `l1.kernel.get_audit_log(limit=SYSCALL_AUDIT_CLI_LIMIT)`, optional agent filter. Returns `{entries}`. |
| `chain` | `cmd_chain` | `<call_id>` | Verify a tool-call chain via `l1.kernel.tool_chain.get_tool_chain().verify(call_id)`; prints per-step fingerprint match. Returns the verification dict. |
| `interrupts` | `cmd_interrupts` | — | Interrupt counts + 10 most recent records (`l1.kernel.interrupt.get_table()`). Returns `{counts, recent}`. |
| `devices` | `cmd_devices` | — | Registered devices (`l1.kernel.device.get_device_manager().list()`). Returns `{devices}`. |
| `status` | `cmd_status` | — | Composed report: calls `health`/`interrupts`/`ps`, then an ops-console summary (`l4.ops_console.get_ops().summary()`, best-effort) and a kernel summary (processes/terminals/audit/devices). Returns `{}`. |
| `sys` | `cmd_sys` | `[path]` | Read a VFS pseudo-file via `l1.kernel.vfs.get_vfs().read(path)` (default `/sys`). Returns the read result dict. |
| `dev` | `cmd_dev` | `[path]` | Read a VFS device node (default `/dev`). Same as `sys` but for `/dev`. |
| `setting` | `cmd_setting` | `[key [value]]` | No args: dump all settings (`get_settings().all()`). One arg: read `key`. Two+: write `key = value` (int/float/str coercion). Returns the settings dict or the set result. |
| `shutdown` | `cmd_shutdown` | — | `l1.kernel.os.get_os().shutdown()`; prints uptime and per-module results. Returns the shutdown result. |
| `backup` | `cmd_backup` | `[tag]` | Snapshot runtime `data_dir` via `l3.services.backup.create_backup(tag=...)`. Returns `{success, backup, copied_files, bytes}`. |
| `backups` | `cmd_backups` | — | List snapshots via `l3.services.backup.list_backups()`. Returns `{success, backups}`. |
| `restore` | `cmd_restore` | `<backup-name>` | Destructive restore via `l3.services.backup.restore_backup(name)`. Returns `{success, restored_files, backup}` or `{success: False}`. |
| `restart` | (lambda) | — | `cmd_shutdown(a)` then `cmd_boot(a)`; no dedicated handler. |

Notes:

- All commands follow the same pattern: lazy module imports inside the
  handler (keeps CLI startup fast and layer-safe), return a dict, print a
  human summary. `l1.kernel` audit/device/process singletons are shared with
  the API gateway.
- `setting` reads/writes the kernel `SettingsCenter` facade
  (`l1.kernel.settings`); runtime writes persist via the injected provider
  (see `docs/configuration/overview.md`).
- Backup/restore operate on the runtime `data_dir` only — never on source
  or git state.

## Agent runtime (`src/l5/agent_runtime.py`)

`AgentRuntime` is the L5-side execution loop contract for user-facing
agents (e.g. an interactive assistant driven by the CLI/REPL):

- `Action` — decorator that registers a callable as an agent action.
- `AgentRuntime.__init__` — creates the runtime and installs default
  handlers (`_register_default_handlers`).
- `on(event, handler)` — register an event handler.
- `tick()` — the main loop step: dispatches pending input/events to
  registered handlers (the heartbeat of the runtime).
- `_on_cancel` / `_on_constitution_update` — built-in handlers for cancel
  and constitution refresh events.
- `status()` — returns the runtime's current status dict.
- `emit(event, ...)` — publish an event to listeners.

The runtime is deliberately thin: it owns no provider calls, prompt/tool
policy, PTY I/O, or worker execution — those remain in L3/L4 adapters (see
`docs/architecture/l3a-central.md`, `docs/architecture/l4-llm.md`).

## Interaction layers (three tiers, one contract)

```
CLI   — scripted, one-shot commands          (existing)
TUI   — full-screen session UI (OpenCode-style, planned; contract-ready)
Desktop — multi-panel formal client          (future)
VSCode — symbiotic extension platform        (future)
```

All three consume the same language-agnostic contract:

- **Sessions**: `/api/v2/l3a/sessions*` (create/list/messages/send/close)
- **Shell**: `/api/v2/shell*` (dispatch input line / autocomplete / command list)
- **Identity**: `/api/v2/auth/*` (login/logout/refresh)
- **Realtime**: SSE `/api/events` + WS bridge (subscribe/rpc)
- **Cards/approvals**: `/api/v2/card*`, `/api/v2/approvals*` (+ event push)
- **Files**: `/api/v2/fs/*`
- **Profile**: `/api/v2/profile*` (user model reference)
- **Settings**: `/api/v2/settings` (incl. `prompt.inject.*` switches)

The TUI layer must be a pure HTTP client (no in-process imports) so the
kernel can be reimplemented in another language (or become multi-language,
e.g. Rust hot-path modules) without rewriting the frontend —
see `cross-cutting.md` for the architecture principle.

## L2 shells vs L5 frontends

- L2 = shell family: dialects (`!intent`, `$cmd`, tools, `/cmd`) over the
  shared engine; `ShellFamily` resolves a frontend → dialect.
- L5 = thin frontends: scripted CLI (`praxis boot`, `praxis card ...`)
  renders the same dict contract.
- TUI/desktop will register their own shells (or bind to `terminal`) and
  render dicts — the engine contract never changes.

## Module map

| File | Responsibility |
|---|---|
| `src/main.py` | Entry point: argv dispatch to `COMMANDS`, `-h` usage, REPL loop with memory shutdown hooks |
| `src/l5/cli.py` | 21 command handlers + `COMMANDS` registry (all return dicts) |
| `src/l5/agent_runtime.py` | `AgentRuntime` execution loop + `Action` decorator + event emit |
