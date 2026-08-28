# Rust Integration-Test Domains

Rust kernel tests are integration targets and live outside `src/`. Each target
keeps its historical Cargo name while its source is grouped by the boundary it
exercises:

| Domain | Scope |
| --- | --- |
| `assembly` | boot plans, port descriptors, and kernel assembly |
| `core` | synchronization, queues, workers, lifecycle, and primitive IPC |
| `network` | bus, peer, health, and notification mechanisms |
| `policy` | capabilities, constitution, identity, reputation, and tool-chain policy |
| `process` | process tables, adapters, constraints, groups, and managed processes |
| `protocol` | wire contracts, schemas, versioning, and conformance vectors |
| `registry` | declarative registries, discovery, and device bookkeeping |
| `runtime` | runtime admission and measurement-only benchmark runners |
| `session` | sessions, AgentLoop routing, snapshots, and execution checkpoints |
| `storage` | state/config layout, persistence, migration, VFS, and atomic stores |
| `terminal` | terminal records, capability probes, and provider-neutral platform metadata |

`Cargo.toml` disables implicit test discovery and explicitly registers every
`tests/<domain>/*.rs` path. This keeps commands such as
`cargo test --test process_group_runtime` stable while making accidental root
level test files fail the Python infrastructure gate.
The same gate rejects inline `cfg(test)`, `#[test]`, `#[bench]`, and test-module
variants in `src/`, including whitespace-formatted attributes.

When a test source basename would collide with a Python reference module, the
source file uses the `kernel_test_` prefix (for example,
`tests/core/kernel_test_event.rs`). The explicit Cargo target keeps its
historical name (`event`) so callers do not need to change their bounded test
commands.

Run a bounded domain slice with:

```bash
cargo test --manifest-path systems/rust-kernel-engine/Cargo.toml --test process_group_runtime
cargo test --manifest-path systems/rust-kernel-engine/Cargo.toml --test session --test agent_loop
```

Run all registered targets as bounded parallel slices with:

```bash
python scripts/py/run_rust_test_domains.py --jobs 4
python scripts/py/run_rust_test_domains.py --domain runtime --jobs 2
```
