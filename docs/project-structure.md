# Project Structure (目录命名规则)

Praxis is an Agent application (an OS-like runtime) that is itself built by
Agents + humans. The repo is therefore strictly partitioned into three
top-level domains: the build environment, the Python reference runtime, and
the clean-break Rust+TypeScript formal runtime. Rust and TypeScript remain
separate runtime artifacts inside that formal domain — keep every new file in
the system or perimeter it belongs to:

## Praxis 本体 (runtime) — the Agent application itself

| Path | Description |
|------|-------------|
| `systems/` | Physical system boundary. See [`systems/README.md`](../systems/README.md) and the machine-readable [`systems/system-boundaries.yaml`](../systems/system-boundaries.yaml). |
| `systems/python-reference-runtime/` | Python reference/prototype: source tree, L1 kernel → L5 user layer (`l1/` … `l5/`); the semantic and test baseline |
| `config/` | Runtime config — **this is what builds Praxis itself**: `praxis.yaml` (kernel, cell, LLM, constitution, gatechain, API), `commands.yaml` (51 L2 commands), `tools.yaml` (78 tools), `skills/` (builtin skills), `discovery/` (structural overrides) |
| `locales/` | i18n: en, zh-CN, ja, ko |
| `.praxis-rules.md` | Constitution rules (parsed by `constitution.py`; repo root) |
| `docs/` | Architecture/config/design/workflow docs — entry points: `docs/configuration/overview.md`, `docs/workflow/branching.md` |
| `systems/typescript-shell-engine/` | Independent TypeScript formal shell/protocol engine; its package and source names are TypeScript-native and do not mirror Python module names |
| `systems/rust-kernel-engine/` | Independent Rust formal kernel engine: `l1-kernel-rs/` implements high-performance L1 primitives. Its integration tests are explicitly grouped under `l1-kernel-rs/tests/<domain>/`, and the candidate remains independent of the Python runtime. |

## 构建环境 (build environment) — external tooling that guides the build

Never imported by a runtime system; never migrated into another system's
source tree. The perimeter may inspect all systems and provide shared test
vectors, but it is not a runtime dependency.

| Path | Description |
|------|-------------|
| `scripts/` | Build/dev scripts: `py/` (python tooling), `sh/` (shell tooling), `js/` (node validation tooling) |
| `tests/` | Test suite (L1–L5, `infra/`, `integration/`, `fixtures/`, `benchmarks/`); all test fixtures live in `tests/fixtures/` |
| `.githooks/` | Self-built git hooks (`commit-msg`, `pre-commit`, `post-checkout`) |
| `.github/` | GitHub Actions CI workflows + `agents/` definition (companion, not a build input) |
| `.gitcode/` | GitCode CI workflow (gray release) |
| `.atomcode/` | AtomCode agent skills/commands (project scope) |
| `.opencode/` | OpenCode agent skills/commands (legacy) |
| `Makefile`, `pyproject.toml`, `systems/rust-kernel-engine/Cargo.toml`, `rust-toolchain.toml`, `Dockerfile`, `docker-compose.yml` | Build config, language workspace metadata, toolchain pin, packaging metadata, container images (kernel/api/sandbox/llm/supervisor) |
| `.pre-commit-config.yaml`, `codecov.yml`, `.gitleaks.toml` | Lint / coverage / secret-scan config |

## 发布 (release) — packaging output

| Path | Description |
|------|-------------|
| `release/` | Release/packaging output placeholder (empty; populated by release tooling, see `scripts/py/bump_version.py`) |

## 运行时数据 (runtime state) — generated, gitignored, never committed

| Path | Description |
|------|-------------|
| `.praxis/` | Runtime state (db/jsonl/sandbox/skills/memories/sockets) — the live `memories/` data lives in `.praxis/memories/` |
| `memories/` | Reserved runtime memory persistence placeholder (kept empty; actual data in `.praxis/memories/`) |
| `.config/` | Runtime keys/secrets (`.config/praxis/keys/`) — **not** the runtime config in `config/` |
| `skills/evolved/` | Project-scope evolved skills (runtime artifact; gitignored; global-scope evolved skills land in `.praxis/skills/evolved/`) |
| `.workspace-timing-data/` | Timing/profiling data |

## 目录命名规则 (directory naming rules)

- **All directories lowercase kebab-case**. Python module files keep
  snake_case; formal Rust leaves use snake_case with a `kernel_` prefix when
  they would otherwise collide with the reference tree, Rust integration-test
  leaves use `kernel_test_` in the same case, and TypeScript leaves use
  domain-specific kebab-case names.
- **`.` prefix = hidden runtime/tool config** (`.praxis/`, `.config/`, `.atomcode/`);
  no prefix = runtime or build-environment content. So `config/` builds Praxis
  itself, while `.config/` belongs to Praxis's runtime.
- **Runtime vs build isolation is physical**: external build tooling
  (`scripts/`, `.githooks/`, `.github/`, CI, Makefile) never migrates into a
  runtime system. The Python, Rust, and TypeScript runtime artifacts never
  import one another's source; build tooling may inspect and drive them.
- **System names are explicit**: `python-reference-runtime`,
  `rust-kernel-engine`, and `typescript-shell-engine` are distinct identities;
  do not recreate `src/`, `crates/`, or `packages/protocol-ts/` aliases.
- **Formal leaf basenames are explicit**: normalized Rust and TypeScript
  source basenames must not reuse a Python reference basename. The check is
  machine-enforced by `python scripts/py/check_system_naming.py`; Rust
  integration-test source leaves and TypeScript `.test.ts` leaves are included
  in the same check. TypeScript test names keep the `.test.ts` suffix and use a
  domain prefix when their normalized stem would otherwise collide.
- **Co-located pairs** (kept separate on purpose):
  | `config/` (runtime config) | vs | `.config/` (runtime keys) |
  |---|---|---|
  | `memories/` (placeholder) | vs | `.praxis/memories/` (live data) |
  | `skills/evolved/` (project scope) | vs | `.praxis/skills/` (global scope) |
  | `tests/benchmarks/` (benchmarks) | vs | `release/` (packaging output) |
