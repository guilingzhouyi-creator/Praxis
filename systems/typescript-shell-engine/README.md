# Praxis TypeScript Shell Engine

This package is the independent TypeScript rewrite perimeter for the Python3
L2 protocol v1 reference. It consumes shared fixtures and keeps L2 protocol
and frontend state local, while the separate `src/l3/` candidate owns only
Agent coordination values and sequencing. Neither area owns Rust process or
terminal state, Python runtime objects, tools, memory, workflow, or policy.

```bash
npm ci
npm test
npm run typecheck
```

Test leaves use Vitest's `.test.ts` suffix and mirror their source module stem
(for example, `tests/terminal-input-telemetry.test.ts` mirrors
`src/terminal-input-telemetry.ts`). When a test stem would collide with the
Python reference namespace, it carries an explicit shell/domain prefix
(for example, `tests/shell-protocol.test.ts`); this is checked by
`make system-naming`.

Commits that stage formal-system sources are additionally gated at pre-commit
time by `check_system_naming.py --staged`: kebab-case directories plus
hierarchy/ownership rules from `config/discovery/naming-rules.yaml` (hard
block, no bypass).

CI pins Node 24; local Makefile targets use the installed compatible Node/npm
toolchain with the committed `package-lock.json` for reproducible installs.

The package may become the L2 session implementation only after the P0
identity, persistence, sequencing, and recovery gates in
`docs/roadmaps/agent-os-3x-closure.md` are green.

The `l3/` directory is the first clean-break TypeScript L3 coordinator slice.
`ts-agent-runtime.ts` validates bounded inputs/actions, isolates identities, emits
defensive lifecycle data, and delegates every side effect through the injected
`RustKernelExecutionPort`. `adapters/rust-protocol-execution-port.ts` carries
that request over `ProtocolBridge.commandPayload()` and maps a Rust `result`
envelope to a receipt. This is candidate-only: provider, prompt, Tool
Pipeline, Memory, Card, Scheduler, Cell/L3A, and recovery domains remain
planned in `docs/roadmaps/l3-ts-rewrite.md`; the Python AgentLoop remains the
reference and rollback implementation.

`l3/providers/decision-provider.ts` is the bounded provider boundary for the
next rewrite slice. It passes detached input/history, a deadline and budget
metadata to an injected provider, propagates caller cancellation, and emits
payload-free latency outcomes. A provider can only return data-only actions;
Rust remains the sole process, terminal, capability, and hard-constraint
authority.

`l3/tools/tool-projection.ts` is the handler-free tool boundary. It accepts
Python-style registry projections, applies deterministic count/description/
parameter bounds, and exposes only public ToolSpec fields to providers. A
`tool_call` action resolves ring/danger from the registered projection and is
sent to Rust as `tool.invoke`; Rust receipts are folded into bounded
ToolResult values. No Python handler, middleware, or executable object crosses
the boundary.

The `engine/rust-agent-loop-terminal.ts` module is a read-only projection of
the Rust terminal-backed AgentLoop value contract. It validates the binding
and opaque frame budgets for L2/frontend rendering or forwarding; it does
not own Rust mailbox state, terminal decoding, PTY/shell selection, AgentLoop
execution, or persistence. Its focused test is
`tests/rust-agent-loop-terminal.test.ts`.

The terminal dialect/session boundary is implemented by
`engine/terminal-shell.ts` and `engine/routing-session.ts`. Its
REPL-neutral output contract is implemented by `engine/terminal-renderer.ts`,
which returns detached `{ role, text }` line records for frontend adapters.
It mirrors the
Python3 L2 input surface (`$` system, `/` commands, pipelines, Direct tools,
L3A intent, and bounded history) while delegating all side effects to the
protocol bridge. Its focused tests are `tests/routing-session.test.ts` and
`tests/terminal-shell.test.ts` plus `tests/terminal-renderer.test.ts`;
interactive REPL input and concrete frontend styling remain frontend
responsibilities.

`engine/frontend-session-adapter.ts` is the shared lifecycle seam for `web`,
`tui`, `desktop`, `vscode`, and `ssh`: it composes attach/replay/ack/detach,
one-line submit, session projection, and renderer output without owning host
state. SSH intentionally uses the TUI projection until a real SSH endpoint is
wired. `engine/terminal-input-controller.ts` is the shared chunk-to-line
boundary for those frontends: it handles LF/CRLF/CR fragmentation, EOF
flushing, UTF-8 byte limits, and serialized `feedInput`/`finishInput` delivery
without reading stdin or creating a PTY. The adapter queue is bounded to 64
pending operations by default and rejects new input at capacity; concrete UI
and REPL loops remain outside this package.
