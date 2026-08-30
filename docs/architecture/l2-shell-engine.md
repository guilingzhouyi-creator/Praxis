# L2 — Shell Engine Layer

Target architecture for the L2 shell family: one **Unified Session Data Layer**
that multiplexes every frontend dialect (web / TUI / lightweight desktop /
VSCode-class IDE / mobile SSH) onto a single Intent/Event stream, backed by one
execution-request bridge into L3 (agents, tools, workflow) and L1 (kernel
capabilities). This document supersedes the "CLI command collection" reality
described in `l2-shell.md`; the audit baseline and staged plan live in
`docs/roadmaps/l2-multifrontend-session-layer.md`.

Current snapshot (2026-08): 43 modules / 5,860 lines; 51 YAML commands + 63
`_cmd_*` handler functions (15 code-only); 74 allowlisted cross-layer imports (67 → L3,
7 → L4). Boundary audit score: 36/100 (see roadmap §1).

The Rust docking candidate exposes a separate TS `session-checkpoint` codec for
the Rust-owned session-store document. It is a typed, fail-closed persistence
adapter only; live session authority, recovery transitions, and production host
selection remain on the Rust/Python host boundary described in the docking
roadmap. `execution-checkpoint` extends this boundary to a read-only view of
the combined Rust Session/Terminal/AgentLoop metadata document. It validates
cross-book identity references, sorted identities, safe integers, and
clean/unclean constraints, and can refresh from disk without exposing a write
operation or recovery authority to TS.

The `rust-agent-loop-terminal` projection is the next narrow TS/L2 seam above
that metadata boundary. It accepts only the versioned Rust
loop/session/terminal binding and opaque terminal frames, validates stream,
sequence, identity, byte, and batch bounds, and returns defensive copies for
rendering or forwarding. The projection rejects identity changes after the
first accepted binding and refuses frame access before a binding exists. It
does not decode terminal bytes, select a shell, create a PTY, dequeue or retry
mailbox work, execute AgentLoop/provider/tool actions, or write Rust state.
Rust remains authoritative for live execution; the focused evidence is
`tests/rust-agent-loop-terminal.test.ts`.

The TS L2 dialect boundary now has a concrete terminal slice:
`engine/routing-session.ts` stores only `L3A`/`DIRECT` routing identity, while
`engine/terminal-shell.ts` classifies and executes one input line through the
existing dispatcher and protocol bridge. Bare text becomes an `l3a_send`
request in the default mode and a direct tool request only after an explicit
Direct target is set. `$` system commands, `/` engine commands, pipelines,
aliases, terminal conveniences, and bounded command history are represented as
data or bridge calls; no TS code spawns a process, invokes a tool handler, or
stores an AgentLoop/Cell handle. The slice is covered by
`tests/routing-session.test.ts` and `tests/terminal-shell.test.ts`; interactive
REPL input and renderer integration remain frontend work.

## Responsibility boundary

L2 is the **kernel-adjacent system-interaction and command-interpretation
layer**: it translates frontend dialects into one canonical data stream and
forwards every side-effecting request through a single execution bridge.

Owns:

- Command parsing (lexer → AST → typed invocation), dispatch, aliases
- Shell session: routing state (mode/cell/agent/session_id), cwd, env, history, job table
- Pipeline *semantics* (parse + graph; never execution)
- IO routing description (stdin/stdout/stderr redirection as data, not syscalls)
- Job control *user semantics* (jobs/fg/bg/kill as requests)
- Built-ins (help/status/history/alias/env/jobs/fg/bg/exit/clear/lang)
- Terminal interaction, help, completion, error presentation
- Frontend adapters, session multiplexing, event projection, session recovery

Never owns (must forward instead):

- Kernel mechanism (process spawn/kill, resource accounting, capability
  authorization, lifecycle authority, persistence, audit, global locks)
- Security / policy authority (approval, ring, sandbox, posture, injection verdicts)
- Agent runtime (agent loop, planning, memory, workflow, scheduler, model choice)
- Domain services (cards, skills governance, settings, CI review, MCP bridge)

## Target architecture

```mermaid
flowchart TB
    subgraph F["Frontends (L5/L4)"]
        WEB["Web GUI"]
        TUI["TUI"]
        DESK["Light desktop (ChatBox-class)"]
        IDE["VSCode-class co-dev platform"]
        SSH["Mobile / SSH"]
    end
    subgraph L2["L2 Shell Engine"]
        AD["Frontend Adapter (dialect → canonical)"]
        SESS["Session (routing state + cwd/env/history/jobs)"]
        IST["Interaction State"]
        CI["Command / Intent"]
        EP["Event Projection"]
        MX["Multiplexing"]
        SR["Session Recovery"]
        EB["Execution Bridge"]
    end
    subgraph L3["L3 (unchanged Agent core)"]
        AL["AgentLoop"]
        TP["Tool Pipeline"]
        WF["Workflow"]
        SC["Scheduler"]
        MEM["Memory"]
        PL["Planning"]
        RS["Runtime State"]
    end
    subgraph L1["L1 Kernel"]
        KC["capability boundary (ProcessPort / GateChain / syscall target)"]
    end
    WEB --> AD
    TUI --> AD
    DESK --> AD
    IDE --> AD
    SSH --> AD
    AD --> SESS
    SESS --> CI
    CI --> EB
    SESS --> EP
    MX --> SESS
    SR --> SESS
    EP --> WEB
    EP --> TUI
    EP --> DESK
    EP --> IDE
    EP --> SSH
    EB -->|"Intent / Event stream"| AL
    EB -->|"invoke_gated"| TP
    AL --> TP
    TP --> KC
    WF --> KC
```

The contract with L3 is **data-only**: one normalized stream
(`intent | command | event | result | stream_chunk | control`). L3 keeps all
agent logic (AgentLoop, Tool Pipeline, Workflow, Scheduler, Memory, Planning,
Runtime State); L2 never imports L3 internals for control flow, only for the
bridge surface listed in `## Contract surfaces`.

## Unified Session Data Layer (protocol v1)

One session owns one logical stream; every frontend is an adapter that
projects the same stream into its own view. The wire format is language-agnostic
(JSON Lines), so the engine can be rewritten in TypeScript without touching L3.

### Message envelope

```json
{"v": 1, "session_id": "s-01J…", "seq": 42, "ts": 1723812345.678,
 "trace_id": "tr-…", "kind": "intent", "payload": {…}}
```

- `seq` — per-session monotonic id; the recovery cursor.
- `trace_id` — reuses the unified trace (L3 `error_bus` convention); never mint new ids.
- `kind`:
  - `intent` — natural-language intent (via `/intent`; legacy `!` prefix accepted) → L3 AgentLoop
  - `command` — structured `/`-command invocation → dispatch table
  - `event` — state/status/stream metadata (task started, tool gated, session switched)
  - `result` — terminal one-shot result (dict contract, render-ready)
  - `stream_chunk` — incremental output (stdout/tool-stream/agent-token)
  - `control` — attach/detach/resume/recovery/ack (session lifecycle, not commands)
  - `ack` — `{"ack_seq": N}` confirming durable consumption

### Conversion rules (dialect → canonical)

| Frontend input | Canonical message |
|---|---|
| `/status` (all frontends) | `command{name:"status", args:[]}` |
| `/scout investigate X@cell/agent` | `intent{type:"scout", task:"…", target:{cell,agent}}` |
| `$ ls -la` | `command{name:"__system", args:["ls","-la"]}` → Execution Bridge → ProcessPort |
| `cat x | grep y` | `command{name:"__pipeline", stages:[…]}` (semantics only; L2 never spawns) |
| web `POST /api/v2/shell` body | same envelope (adapter wraps/unwraps HTTP) |
| mobile SSH line | same envelope (transport = stdio/SSH channel) |

### Session multiplexing & recovery

- One `ShellSession` may bind N frontend views (multiplexing); each view holds
  an `ack_seq` cursor. `Event Projection` renders the shared session state
  into per-frontend shapes (web JSON / TUI table / desktop rich / IDE LSP-ish).
- Recovery: `control{kind:"recovery", last_acked: N}` — L2 replays the
  un-acked window from its bounded outbox, then re-attaches. Session truth
  stays in L3 (`SessionManager`) and L1 (kernel state); L2 only carries the
  routing view + outbox, so an L2 restart never forks agent state.
- Interrupted commands / orphan jobs: the L2 job table is a *projection* of
  L3/L1 job truth; on restart L2 re-syncs by query, never by guessing.

### Reference implementation & contract pins (landed)

The protocol is not just a design: a pure Python reference, machine-readable
schemas, contract-pin tests, and a stdio host are already in the tree. All
are **additive** - no existing engine behavior was changed.

| Asset | Path | Purpose |
|---|---|---|
| Envelope reference | `systems/python-reference-runtime/l2/protocol/envelope.py` | pure make/validate/encode/decode + `Outbox` (bounded replay, `maxlen=1024`) + `SessionCursor`; stdlib-only, zero singletons, zero I/O; TS mirror uses simple array (`push/shift/filter`) for auditability |
| JSON Schemas | `systems/python-reference-runtime/l2/protocol/schema.py` | Draft-07 envelope + per-kind payload schemas - the TS zod/io-ts mirror target |
| TS-neutral records | `systems/python-reference-runtime/l2/protocol/records.py` | versioned `SessionIdentity`, `EventEnvelope`, `SessionMessage`, `ToolFailure`, `DecisionSummary`, and `EvidenceRef`; unknown fields are ignored, unsupported versions fail closed, and CoT is excluded |
| Record fixtures | `tests/fixtures/protocol_v1_records.json` | deterministic v1 samples consumed by Python tests and the planned TypeScript/vitest mirror |
| TypeScript mirror | `systems/typescript-shell-engine/src/{wire-records,wire-envelope}.ts` | read-only parity implementation; it consumes the shared fixture and does not own L2/L3 runtime state |
| Stdio host | `systems/python-reference-runtime/l2/protocol/host.py` (`python -m l2.protocol.host`) | JSONL bridge over the existing `l2.l2_shell.dispatch`; command/intent/control in, result/event/ack out; fail-closed on bad input |
| Rust host candidate | `systems/rust-kernel-engine/l1-kernel-rs/src/bin/rust-protocol-host.rs` + `systems/typescript-shell-engine/src/engine/transports/rust-host.ts` | opt-in JSONL child host selected by `PRAXIS_RUST_HOST`; TS owns only process wiring, stderr capture, and immediate pending-request failure on child/input close, while Rust owns candidate routing/gates; production default remains Python until R4/R5 cutover |
| Contract pins | `tests/l2/test_protocol_v1.py` | envelope round-trip, validation, outbox cursor/ack/cap, schema alignment, host smoke tests |
| Dispatch JSON contract | `tests/l2/test_dispatch_contract.py` | every render-ready dispatch result must survive `json.dumps`; stable shapes for /help /lang /history /sysinfo, unknown-command, pipeline, alias |

Usage (the future `bridge.ts` speaks exactly this):

```bash
$ printf '%s\n' '{"v":1,"session_id":"s-1","seq":1,"ts":0.0,"kind":"command","payload":{"name":"lang"}}' \\
    | python -m l2.protocol.host
{"kind":"result","payload":{"available":["en","ja","ko","zh-CN"],"locale":"en","success":true},...}
{"kind":"ack","payload":{"ack_seq":1},...}
```

TS mirror strategy: `systems/typescript-shell-engine` ports `envelope.py` and `records.py`
semantics 1:1 into `wire-envelope.ts` and `wire-records.ts`, loads
`tests/fixtures/protocol_v1_records.json`, and runs parity expectations in
Vitest. The Python tests and fixture double as the TS spec; this package is
read-only until the P0 recovery gates are complete.
The host is the integration seam: the transport factory can spawn the Python
reference or the Rust candidate as a child process, selected only by the
explicit `PRAXIS_RUST_HOST` switch. `bridge.ts` and the L2 engine remain
host-agnostic and only speak protocol v1; Rust activation does not grant L2,
AgentLoop, provider, or production boot authority.
The TS bridge constrains its optional sequence wrap bound to safe integers and
uses the safe wire bound when no explicit bound is configured, so no generated
envelope loses precision at the JavaScript number boundary. Envelope validation
applies the same safe-integer rule to inbound `seq`, `ack_seq`, and
`last_acked` in TS, Python reference, and Rust host adapters. Rust mechanisms
may retain wider `u64` counters internally, but the v1 JSONL wire never emits
an ambiguous value.
Managed transports fail pending requests immediately when their input source
or child exits, and `close()` is idempotent; reconnection remains an explicit
`ConnectionManager` concern rather than an implicit Python fallback.
Synthetic protocol-fault results on the `"-"` session also close a pending
line request without an ack; `ProtocolBridge` then surfaces the session error
instead of converting a malformed frame into a timeout.

### Protocol v1 conformance rulings (2026-08, normative)

Authority model: **`systems/typescript-shell-engine` is the normative L2 protocol
authority**; the Rust kernel (`systems/rust-kernel-engine/l1-kernel-rs`) must reproduce TS
canonical output byte-for-byte; `systems/python-reference-runtime/l2/protocol` (Python) is a frozen
legacy reference retained only until the G6 cut-over retires it. Golden
vectors are frozen from the TS engine, not from the Python host.

| # | Ruling | Rationale |
|---|---|---|
| R1 | `Outbox.ack` is non-destructive: it advances only the ack cursor; replay windows survive until eviction. Replay = messages with `seq > max(last_acked, after_seq)`. | multi-view recovery; one view's ack must never erase another view's window |
| R2 | `seq` is monotonic **per session**. Response sequence counters are per-session state, never process-global. | envelope contract "Monotonic session sequence"; restart aliasing |
| R3 | `ts` must be a finite number. Encoders reject non-finite values (`allow_nan=False` / serde finite check / `Number.isFinite`). | Python stdlib JSON otherwise accepts/emits `NaN`, producing frames Rust/TS cannot parse |
| R4 | Host-derived authorization fields (`approved`, `pre_approved`, `full_power`, `harness_auto_approved`) are **forbidden in inbound payloads**; ring/danger MAY be declared inbound as gate inputs but confer no authority. Decoders reject banned fields. | GateRequest authorization inputs are adapter-derived; wire self-approval defeats G4 |
| R5 | Frame limit is 1 MiB per JSONL line on every host (Rust and Python alike). Oversize frames are rejected before parse. | DoS bound; parity with `ProtocolHostConfig::max_frame_bytes` |
| R6 | Dialect routing order: `$` system → `/` engine command → `\|` pipeline → direct tool → L3A intent. Argument splitting is quote-aware (shlex-compatible subset). | a `\|` inside a quoted argument or command payload must not misroute into the pipeline |
| R7 | Gate denials, unregistered commands, and unwired executors produce `result{success:false}` envelopes on the wire — not transport-level errors. Only undecodable/oversized frames fail at the transport layer. | clients must receive structured rejections; fail-closed |
| R8 | Wire-contract constants (`PROTOCOL_VERSION`, `OUTBOX_MAXLEN`, frame limits, kind sets) are exempt from the params rule and inlined identically in all three implementations. | contract constants mirror across languages by design |
| R9 | TS `SessionMultiplexer` keeps a bounded local event mirror (default 16,384; configurable for tests). It first evicts the shared acknowledged prefix, then evicts the oldest entries if a stalled view reaches capacity; host replay remains authoritative. | a disconnected or stalled frontend cannot grow client memory without bound |

## Execution bridge

Every side-effecting request exits L2 through exactly one bridge:

| Request | Bridge target | Boundary |
|---|---|---|
| tool call (`!` intent, tool line, agent tool request) | `l3.tool_system.invoke.invoke_gated(…, interactive=True)` | L3 Tool Pipeline (clearance/approval/rate/constitution/gatechain/sandbox) |
| `$` system command | `l1.kernel.ports.get_process_port().run()` | L1 ProcessPort |
| slash control command (settings/cards/skills/model/…) | L3 **command bridge** (to be built; replaces 63 direct imports) | L3 service facade |
| event emission | kernel event API only if L1 owns the event; otherwise L3 bus | — |

L2 itself performs no direct filesystem writes, no network I/O, no
`subprocess.Popen`, no tool-handler invocation, no DB mutation.

## Module inventory (audit verdicts)

| Module (today) | Verdict | Target |
|---|---|---|
| `l2_shell/__init__.py` dispatch/alias | keep (A) | split: `parser.ts` + `dispatcher` |
| `shells/{base,family,session}.py` | keep (A) | `interactive-session.ts` state machine |
| `shells/terminal.py` dialect | keep (A) | adapter for terminal frontend |
| `l2_shell/completer.py`, `shell_completer.py`, `i18n.py` | keep (A/F) | UX layer |
| `l2_shell/commands/{common,system,connect}.py` | keep shell built-ins; move control commands | split per verdict |
| `l2_shell/commands_settings.py`, `model.py`, `memory.py`(card/spawn/kill), `ci.py`, `harness.py`, `test_auto.py`, `extra_mcp.py`, `extra_security.py`, `departments.py`, `identity_binding.py`, `l3a.py` | **move out** (B/E/D) | L3 admin surface behind command bridge |
| `selector.py` | **move policy out** | keep only "user picks agent"; injection verdict → L3 |
| `output_guard.py` | move policy; keep presentation filter | L3 policy + render guard |
| `shell_session.py` (Popen TerminalManager) | **delete** (dead code; 0 callers) | never re-add; long-lived processes → L1 platform port |
| `_l3a_intent` (broken import `l2.l2_shell.cell`) | **fix or delete** | route through L3 command bridge |

## Completeness matrix (target)

| Capability | Current | Target |
|---|---|---|
| Lexer / Parser / AST / error recovery | MISSING | COMPLETE (TS `parser`) |
| Command registry + dispatch | COMPLETE (owner: L1, writers ×3) | COMPLETE (registry owner: L2, single writer) |
| Built-ins (cd/pwd/env/export/alias/jobs/fg/bg/exit/…) | PARTIAL (stubs) | COMPLETE |
| External commands | PARTIAL (`$` only) | COMPLETE (bridge-integrated) |
| Session lifecycle + cwd/env/history | PARTIAL/MISSING | COMPLETE |
| Job control | MISSING | COMPLETE (projection of L3/L1 truth) |
| Pipeline (parse+graph; no exec) | MISSING (fake arg-chain) | COMPLETE |
| IO redirection | MISSING | COMPLETE (as data) |
| Interactive UX | PARTIAL | COMPLETE |
| Execution bridge | PARTIAL (tool side fixed in WT) | COMPLETE (single bridge) |
| Recovery (interrupt/orphan/restart) | MISSING | COMPLETE |

## TS rewrite mapping

| Today (Python) | TS module | Notes |
|---|---|---|
| `dispatch` + `shlex` | `parser.ts` + `dispatcher.ts` | pure; no side effects |
| `ShellSession` / `ShellFamily` | `engine/routing-session.ts` + `engine/session-family.ts` (SessionView remains the protocol projection) | JSON-serializable routing state; no upper-layer handles |
| `shells/*` | `engine/terminal-shell.ts` + `engine/transports/*` + `interactive-session.ts` projections | dialect execution is landed; real frontend adapters and REPL renderer remain |
| `commands/*` built-ins | `builtins/*.ts` | pure functions over session |
| `l2_shell/state.py`, `completer.py` | `state.ts`, `complete.ts` | — |
| execution calls (L3/L1) | `bridge.ts` (single client) | speaks protocol v1 to the Python L3 host (stdio/WebSocket/HTTP); **L3 Agent logic stays Python** |
| `i18n.py` | `locale-catalog.ts` | same locale data |

The TS engine is a *host-agnostic frontend of L3*: it never re-implements
AgentLoop/Tool Pipeline/Workflow/Scheduler/Memory/Planning. The L3 host remains
the single authority; TS L2 is a pure projector + dispatcher + bridge client.

### Phase A local projection modules (2026-08-28)

Pure local metadata/display projections added to close the mapping gaps below;
all are render-only — the host keeps execution and verdict authority.

| Module | Mirrors (Python) | Responsibility |
|---|---|---|
| `engine/command-catalog.ts` | `l2/commands.py` metadata + `config/commands.yaml` | Parses the shared YAML subset (commands, aliases, args, examples), alias reverse index, revision counter; bounded name cache |
| `engine/terminal-view.ts` | `l2/shells/terminal.py` result shapes | Normalized dict projections for help/tools/intent/scout/system/tool views |
| `engine/agent-selector.ts` (preconnectImpact + riskLevelOf) | `l2/selector.py` `preconnect()` result | Display-safe verdict projection and injection-risk grading at the reference thresholds (0.3 / 0.7) |

Integration: `builtins.ts` renders full-surface `/help` from the catalog;
`route.ts` resolves catalog aliases of local handlers before bridging and
routes local dispatch through a session id; `command-completion.ts` merges
catalog command names/aliases into candidates; `command-groups.ts` registers
all eight domains (settings/system/memory/model/selector/card/l3a/tool) with
local arity validation; `locale-catalog.ts` carries the terminal/selector
display keys, value-locked to `locales/en.yaml` by a parity test.

### Phase A backend hardening (2026-08-28)

| Area | Change |
|---|---|
| `connection-manager.ts` | Closeable transports are released on disconnect and when a failed probe is replaced (no lingering children/sockets); close is best-effort and idempotent |
| `session-manager.ts` / `interactive-session.ts` | `SessionManager.detach` releases the per-session multiplexer when its last view leaves; `SessionView.ack`/`detach` complete the view lifecycle (monotonic ack, cursor reset) |
| `l3-bridge-interface.ts` | `IL3Bridge.session` domain completes the typed control plane (attach/detach/ack/replay/resume) |
| `projection-cache.ts` | FIFO-bounded at 256 entries instead of unbounded growth |

## Contract surfaces

- **L3**: `invoke_gated` (tools), L3 command bridge (control commands, to be
  built), L3A session lifecycle via bridge, data-only Intent/Event stream.
- **L1**: `ProcessPort.run` (`$`), `CommandRegistry` (migrate to L2),
  params constants, kernel event API only where L1 owns the event.
- **Frontends**: `POST /api/v2/shell` (web), TUI adapter, desktop adapters,
  mobile/SSH adapter — all speak protocol v1.
- **Never**: direct tool handler calls (`_execute_tool_spec` stays private),
  `subprocess.Popen` in L2, private internals of L4 providers, direct
  settings/card/skill mutation without the bridge.

## Related docs

- `docs/roadmaps/l2-multifrontend-session-layer.md` — audit baseline + staged plan
- `docs/roadmaps/kernel-boundary-audit.md` — L1 twin audit (Rust baseline)
- `docs/roadmaps/frontend-kernel-roadmap.md` — frontend matrix + kernel Rust sink
- `docs/roadmaps/multilang-migration.md` — run_code/PTC TS slot
- `docs/architecture/l2-shell.md` — current (superseded) shell description
- `docs/architecture/l1-kernel.md` — kernel boundary this layer builds on
