# L5 — User Layer

Entry points and user-facing contract. 2 files / 599 lines.

## CLI entry (`main.py` → `l5/cli.py`)

```
python src/main.py boot | health | status | ps | card <intent> |
                     tools | audit | chain | interrupts | devices
```

`cli.py` commands return dicts and print summaries — the same dicts a TUI
would render.

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
