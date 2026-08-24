# L4 — Bridge Layer

The boundary: HTTP API (368 routes), LLM engine, realtime channels,
sandbox, auth, filesystem, RPC. 113 files / 23,539 lines; 34 handler
modules.

## Responsibility boundary

- Exposes the kernel/cell world over **versioned HTTP contracts**
  (`/api/v2/*`), SSE/WebSocket event streams, and RPC.
- Implements port adapters (Auth/WS/RPC/FS) and LLM providers.
- No business logic beyond translation/aggregation.

## Subsystems

| Subsystem | Files | Role |
|-----------|-------|------|
| `api/` | gateway (route index + signature cache), routes (368), middleware, endpoints manifest (validate) | HTTP surface |
| `api_handlers/` | 34 modules | dict-in/dict-out handlers per domain |
| `llm/` | engine + providers (OpenAI/Anthropic/DeepSeek/Ollama/mock), `http_pool` keep-alive | model calls, effort-tier normalization, capability probes |
| `sse/` | `sse_bridge.py` | one-way event stream (`/api/v2/events`, event-type filter) |
| `ws/` | `ws_bridge.py` (websockets.sync, `API_WS_PORT=8081`) | bidirectional: subscribe/unsubscribe/rpc messages |
| `rpc/` | protocol + transport + `server.py` (`RPC_SERVER_PORT=42110`) | distributed method invocation |
| `sandbox/` | COW isolation + exec sandbox (per-thread event loop) | safe tool execution |
| `sandbox/` (diff) | `sandbox_diff.py` (three-tier build/review/conflict), `diff_codec.py` (structure-aware hunk frames, `PD2`/`PDZ`), `diff_dict.py` (shared Zstd dictionary), `diff_persist.py` (ring + JSONL + zstd-19 R4 archive) | structured diff + tiered compression |
| `vault/` | `credential_vault.py` + `auth.py` (AuthPort adapter: HMAC token lifecycle) | secrets + identity |
| `lsp/` `search/` `mcp_bridge.py` `cron_scheduler.py` `supervisor.py` `notify.py` `user_session.py` | editor/lexical/plugin-adjacent services | auxiliary bridges |

## Realtime channels (frontend contract)

```
SSE  /api/events               one-way push (EventBus on_any)
WS   ws://host:8081            subscribe/unsubscribe/rpc (bidirectional)
     {"type":"rpc","method":"/api/v2/card/submit","params":{...}}
     → {"type":"rpc.result","method":...,"data":{...}}
```

WS `rpc` routes full API paths to POST handlers (module-path refs only);
SSE stays the notification bus. Both deliver card/approval events without
polling (CARD_PENDING / APPROVAL_REQUIRED / APPROVAL_RESPONDED).

```mermaid
sequenceDiagram
    participant F as Frontend (TUI/desktop/TS)
    participant W as WS bridge :8081
    participant A as API handlers
    participant B as EventBus

    F->>W: {"type":"subscribe","events":["card.pending","approval.required"]}
    F->>W: {"type":"rpc","method":"/api/v2/card/submit","params":{...}}
    W->>A: route to POST handler (dict in)
    A-->>W: {"type":"rpc.result","method":...,"data":{...}}
    W-->>F: rpc.result
    B-->>W: event (CARD_PENDING)
    W-->>F: {"type":"event","event":"card.pending","data":{...}}
```

## Auth flow (login state)

```mermaid
sequenceDiagram
    participant F as Frontend
    participant A as /api/v2/auth/*
    participant S as AuthService (AuthPort)
    participant G as GateChain/security gates

    F->>A: POST /auth/login {identity}
    A->>S: issue_token (HMAC payload + expiry + revocation set)
    A-->>F: {token, expires_at}
    F->>A: API calls with token
    A->>S: verify_token
    S-->>A: {valid, identity}
    A->>G: security checks use port "auth" (no stub)
    F->>A: POST /auth/refresh | /auth/logout (revoke)
```

**Fail-closed auth (W2.1):** with no static token configured and no AuthPort
reachable, requests are DENIED (`AUTH_DENY_WHEN_UNCONFIGURED`, default True).
Explicit opt-out for open deployments: `PRAXIS_AUTH_OPEN=1`.

## Auth contract

- `POST /api/v2/auth/login|logout|refresh` — HMAC-signed token lifecycle
  (`AuthService` implements `AuthPort`, self-registers on port `"auth"`).
- `central_security` verifies `user_token` via the port (no hardcoded stub).

## FS contract

- `GET /api/v2/fs/tree|read`, `POST /api/v2/fs/watch|unwatch` — via
  `FilesystemPort` adapter (`l3/services/fs_adapter.py`, mtime-poll watch).

## Gateway fast paths

- O(1) exact-match route index (lazy rebuild), cached
  `inspect.signature(handler)` per handler, persistent LLM connections
  (`http_pool`), per-thread sandbox event loops.

## Contract discipline

- Manifest `validate()` (api_endpoints) enforces kebab-case paths, `{param}`
  names mirroring handler kwargs, no trailing-slash params — run
  `python -m l4.api.api_endpoints` before pushing API changes.
- Version bumps are atomic (pyproject + AGENTS.md + docs).

## CI review API (card-triggered automation)

The CI review module (`ci.py` + `ci_review.py`) exposes a control plane for
the card-triggered pipeline (`l3-card-lifecycle.md` §4a):

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/ci/reviews` | query CI review reports |
| `GET` | `/api/v2/ci/reviews/{card_id}` | single card CI review report |
| `POST` | `/api/v2/ci/reviews/{card_id}/rerun` | re-run CI review for a card |
| `GET` | `/api/v2/ci/config` | switch state + permissions |
| `PUT` | `/api/v2/ci/config` | toggle runtime switch (control-plane gated) |

Writability is governed by `config/praxis.yaml` `ci.control.api.writable`
(API surface) and `ci.control.shell.writable` (L2 `/ci` command surface).
L2 surface: `/ci set|toggle` via `l2_shell/commands/ci.py`.

## Security evidence API (attack-posture audit)

Read-only projection of the evidence chain (`l3/tool_system/
security_evidence.py`, see [l3 security-evidence.md](security-evidence.md)):

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/security/evidence/chains` | chain index (kinds, open/closed, verdicts) |
| `GET` | `/api/v2/security/evidence` | filtered evidence query (chain_id / skill / phase / decision) |
| `GET` | `/api/v2/security/evidence/report` | markdown report: timeline + findings + verdict + fixity |

## Diff subsystem (structure-aware frames)

The diff pipeline (`sandbox_diff.py` three-tier build/review/conflict, see
[`Subsystems`](#subsystems) row) is backed by a tiered, structure-aware
frame family — all frames carry an 8-byte plaintext header
(`frame_type | bitmask | threshold_score | hunk_count`, `diff_frame.py`)
so L3 bypass paths read hunk counts without decompressing:

- **Hunk frames** (`diff_codec.py`): dictionary-coded hunks (type/semantic
  → byte codes, row numbers → deltas). Compression tiers: shared Zstd
  dictionary (`diff_dict.py`, samples dir declared in `config/discovery`)
  → `PDZ`; zlib fallback `PD2`; L3 archive Zstd-19 (`PDZ19`).
- **AST tree-edit frames** (`ast_edit.py`): semantic INS/DEL/MOV/UPD edit
  scripts over normalized ASTs (Varint/Zigzag coded) for languages that
  declare `tree_backend: python_ast` in `config/discovery/diff_languages.yaml`
  (magic `PDA`); unparseable or unlisted languages fall back to hunk frames.
- **Review context**: the review tier attaches LSP diagnostics
  (`_lsp_diagnostics`) and AST symbols (`SymbolSearch.symbols_in_file`);
  the HTN-C identity hit (`match_identity` on the driving intent) rides the
  `REVIEW_REWORK` message as `hit_identity` so the producing peer knows
  which identity must rework.
- **Persistence**: `diff_persist.py` JSONL append + `recover()` crash
  recovery with per-hunk attribution.
