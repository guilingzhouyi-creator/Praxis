# Project Structure (目录命名规则)

Praxis is an Agent application (an OS-like runtime) that is itself built by
Agents + humans. The repo is therefore strictly partitioned into four layers —
keep every new file in the layer it belongs to:

## Praxis 本体 (runtime) — the Agent application itself

| Path | Description |
|------|-------------|
| `src/` | Source tree, L1 kernel → L5 user layer (`src/l1/` … `src/l5/`); the OS implementation |
| `config/` | Runtime config — **this is what builds Praxis itself**: `praxis.yaml` (kernel, cell, LLM, constitution, gatechain, API), `commands.yaml` (51 L2 commands), `tools.yaml` (78 tools), `skills/` (builtin skills), `discovery/` (structural overrides) |
| `locales/` | i18n: en, zh-CN, ja, ko |
| `.praxis-rules.md` | Constitution rules (parsed by `constitution.py`; repo root) |
| `docs/` | Architecture/config/design/workflow docs — entry points: `docs/configuration/overview.md`, `docs/workflow/branching.md` |
| `packages/` | TypeScript workspaces: `packages/protocol-ts/` implements the wire protocol and TS shell engine |
| `crates/` | Rust workspace: `crates/l1-kernel-rs/` implements the high-performance L1 kernel primitives |

## 构建环境 (build environment) — external tooling that guides the build

Never imported by the runtime; never migrated into `config/` or `src/`.

| Path | Description |
|------|-------------|
| `scripts/` | Build/dev scripts: `py/` (python tooling), `sh/` (shell tooling), `js/` (node validation tooling) |
| `tests/` | Test suite (L1–L5, `infra/`, `integration/`, `fixtures/`, `benchmarks/`); all test fixtures live in `tests/fixtures/` |
| `.githooks/` | Self-built git hooks (`commit-msg`, `pre-commit`, `post-checkout`) |
| `.github/` | GitHub Actions CI workflows + `agents/` definition (companion, not a build input) |
| `.gitcode/` | GitCode CI workflow (gray release) |
| `.atomcode/` | AtomCode agent skills/commands (project scope) |
| `.opencode/` | OpenCode agent skills/commands (legacy) |
| `Makefile`, `pyproject.toml`, `crates/Cargo.toml`, `rust-toolchain.toml`, `Dockerfile`, `docker-compose.yml` | Build config, language workspace metadata, toolchain pin, packaging metadata, container images (kernel/api/sandbox/llm/supervisor) |
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

- **All directories lowercase kebab-case** (module *files* keep snake_case).
- **`.` prefix = hidden runtime/tool config** (`.praxis/`, `.config/`, `.atomcode/`);
  no prefix = runtime or build-environment content. So `config/` builds Praxis
  itself, while `.config/` belongs to Praxis's runtime.
- **Runtime vs build isolation is physical**: external build tooling
  (`scripts/`, `.githooks/`, `.github/`, CI, Makefile) never migrates into
  `config/` or `src/`.
- **Co-located pairs** (kept separate on purpose):
  | `config/` (runtime config) | vs | `.config/` (runtime keys) |
  |---|---|---|
  | `memories/` (placeholder) | vs | `.praxis/memories/` (live data) |
  | `skills/evolved/` (project scope) | vs | `.praxis/skills/` (global scope) |
  | `tests/benchmarks/` (benchmarks) | vs | `release/` (packaging output) |
