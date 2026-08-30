# Praxis TypeScript Shell Engine

This package is a read-only TypeScript parity implementation of the Python3
L2 protocol v1 reference. It consumes the shared fixture at
`tests/fixtures/protocol_v1_records.json` and does not own L2, L3A, AgentLoop,
tool, memory, or workflow state.

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

The `engine/rust-agent-loop-terminal.ts` module is a read-only projection of
the Rust terminal-backed AgentLoop value contract. It validates the binding
and opaque frame budgets for L2/frontend rendering or forwarding; it does
not own Rust mailbox state, terminal decoding, PTY/shell selection, AgentLoop
execution, or persistence. Its focused test is
`tests/rust-agent-loop-terminal.test.ts`.
