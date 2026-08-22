# Praxis Protocol TypeScript Mirror

This package is a read-only TypeScript parity implementation of the Python
L2 protocol v1 reference. It consumes the shared fixture at
`tests/fixtures/protocol_v1_records.json` and does not own L2, L3A, AgentLoop,
tool, memory, or workflow state.

```bash
npm ci
npm test
npm run typecheck
```

CI pins Node 24; local Makefile targets use the installed compatible Node/npm
toolchain with the committed `package-lock.json` for reproducible installs.

The package may become the L2 session implementation only after the P0
identity, persistence, sequencing, and recovery gates in
`docs/roadmaps/agent-os-3x-closure.md` are green.
