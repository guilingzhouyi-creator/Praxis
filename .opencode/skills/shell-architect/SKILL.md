---
name: shell-architect
description: Use when writing or modifying Praxis L2 shell code — ShellFamily dialect adapters, l2_shell dispatch engine, commands.yaml/commands.py handlers, i18n, shell_completer, selector, or per-session ShellSession state.
---

## Overview

Architecture guide for the L2 shell family (`systems/python-reference-runtime/l2/`). Linux-model design: one stable engine contract (`l2_shell/` dispatch), many shell dialects (`shells/`) translating frontend dialects into it. A new frontend registers a new shell — the engine never changes.

## Module Map

- **Shell family**: `shells/base.py` (`Shell` ABC — `run(text, session) -> dict`, `create_session()`), `shells/family.py` (`ShellFamily` registry + frontend bindings, revision-based), `shells/session.py` (`ShellSession` — per-session mode L3A/Direct, cell, agent, session id), `shells/terminal.py` (`TerminalShell`: `!intent` → L3A, `$cmd` → system, `/cmd` → engine, tool calls)
- **Engine**: `l2_shell/` — `dispatch(text, session=None) -> dict` (| pipeline, / commands, Direct mode, L3A), `__main__.py` (interactive loop), `commands/` (per-domain handlers returning dicts), `commands_settings.py`, `completer.py`, `output_guard.py`, `state.py`
- **Support**: `i18n.py` (en/zh-CN/ja/ko cached adapter), `shell_completer.py` (tab completion + aliases), `selector.py` (agent selector, locked index)

## Core Conventions

- **Interaction model**: `!<intent>` → L3A direct session (cardwrite path); `!<intent>@cell/agent` → routed direct session; `$ <command>` → raw system command via `get_process_port().run`; `<tool> <args>` → tool execution (aliases e.g. rf→read_file); `/command` → engine dispatch (dict results).
- **Shell family lifecycle**: members declared in `config/discovery/shells.yaml` (module + class per member); boot step `init_shells` (L3) instantiates them into the family from the three-layer config: params defaults ← discovery YAML ← praxis.yaml `shells:` deployment overrides. No shell is hardcoded — adding a frontend means declaring a shell in YAML.
- **Handlers are the frontend contract**: CLI/TUI/API render the same dict-returning surfaces. Handlers live in `systems/python-reference-runtime/l2/l2_shell/commands/*.py` (YAML: `config/commands.yaml` — 51 commands; code-registered `_cmd_*` handlers).
- **Session state**: L3A/Direct mode lives per-session on `ShellSession`; reset per test via conftest `_RESETS` (`l2.shells.family`, `l2.l2_shell.state`). `l2_shell/state.py` is a thin accessor over the family default shell's session — NOT a second process-global state source; new code passes a `ShellSession` explicitly to `dispatch(text, session=None)`.
- **Bottom-layer boundary**: engine only calls port/platform abstractions (`ProcessPort`, `FilesystemPort`, `WorkerPort`) — never raw `os`/`subprocess` — so swapping adapters (Python → Rust) is invisible to `dispatch` and every shell dialect.
- **HTTP contract** (language-agnostic): `POST /api/v2/shell` → `dispatch(text, session)`; `GET /api/v2/shell/autocomplete`; `GET /api/v2/shell/commands` — handlers in `l4/api_handlers/api_handlers_agent.py`.
- **Magic numbers** (timeouts, truncation) come from params — never inline.

## Tests

- `python -m pytest tests/l2/test_l2_shell.py -x -q`
- i18n + command counts drift-gated by doc-stats (`make doc-stats`)
