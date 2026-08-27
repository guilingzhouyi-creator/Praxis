# Praxis system layout

Praxis is maintained as three top-level domains:

1. the repository build environment, which observes and drives every system;
2. the Python reference runtime, which is the technical prototype and semantic
   baseline;
3. the clean-break formal runtime, whose Rust kernel and TypeScript shell are
   separate artifacts and separate process boundaries.

The directory names are intentionally explicit so a Rust/TypeScript rewrite
cannot be mistaken for the Python reference runtime. Rust and TypeScript stay
separate inside the formal domain: the grouping is conceptual, not a shared
source tree or an import relationship.

| System | Directory | Artifact identity | Role | Runtime authority |
|---|---|---|---|---|
| Python reference runtime | `systems/python-reference-runtime/` | `praxis-python-reference-runtime` | Complete five-layer prototype and semantic baseline | Current prototype only |
| Rust kernel engine | `systems/rust-kernel-engine/` | `praxis-rust-kernel-engine` | Clean-break Rust L1 kernel and mechanism candidates | Candidate until an explicit cutover |
| TypeScript shell engine | `systems/typescript-shell-engine/` | `@praxis/typescript-shell-engine` | TypeScript L2 shell/protocol engine and frontend adapters | Read-only frontend/protocol side |

The repository root is the build environment. `scripts/`, `tests/`,
`config/`, `docs/`, CI workflows, hooks, and language toolchain metadata
operate on the systems but are not imported by their runtime source. It is
deliberately kept at repository scope rather than copied into a runtime
directory.

## Dependency boundary

Runtime dependencies point inward within a system only:

```text
Python reference runtime  ── semantic baseline ──> build/test perimeter
Rust kernel engine         ── candidate outputs ──> build/test perimeter
TypeScript shell engine   ── candidate outputs ──> build/test perimeter
```

There is no runtime source-to-source dependency between the Python, Rust, and
TypeScript artifacts. Cross-language checks are process-level or fixture-level
tests in the build perimeter. `tests/fixtures/` contains small,
language-neutral contract and semantic vectors; it is not runtime state and is
never imported by production code.

The Python system may read repository configuration and locales through its
host bootstrap. Rust and TypeScript do not read the Python source tree,
repository `config/`, or each other's source tree. Their candidate binaries
receive configuration and host capabilities explicitly at their process
boundary.

## Naming rules

- Use lowercase kebab-case for system directories.
- Keep Python module files snake_case under `python-reference-runtime`.
- Keep Rust crate/source names Rust-native under `rust-kernel-engine`.
- Keep TypeScript package/source names TypeScript-native under
  `typescript-shell-engine`; do not recreate Python `l1`–`l5` package names as
  TypeScript or Rust modules.
- Treat the system directory and artifact identity as the namespace boundary:
  leaf files may retain semantic names such as `event` or `session` when their
  language-native package path is different. A Rust/TypeScript artifact must
  never reuse the Python artifact name or a legacy package root.
- Do not add compatibility aliases named `src/`, `crates/`, or
  `packages/protocol-ts/`. The boundary checker rejects those legacy roots.
- Build manifests may describe their own artifact only; path dependencies to
  another runtime artifact are forbidden. The build environment may inspect
  and test all artifacts, but runtime code must not import build tooling.

The authoritative machine-readable version of these rules is
`systems/system-boundaries.yaml`. Run `make system-boundaries` after moving or
adding a runtime file.
