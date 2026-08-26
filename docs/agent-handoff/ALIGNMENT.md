# Alignment State — live

> Updated whenever an agent registers a shared-file change or a merge lands.
> Read before committing; append before pushing (see `README.md` rules).

## Active worktrees (2026-08-25)

| Worktree | Branch | Domain | Notes |
|---|---|---|---|
| praxis (main) | main | — | stable |
| praxis-kernel-next | root-kernel-next | K kernel | active |
| praxis-kernel-merge | root-kernel-converge | K kernel | active |
| praxis-kernel-preflight | root-kernel-preflight | K kernel | 170 commits ahead |
| praxis-session-id | s-session-identity | S sessions | active |
| praxis-gate-hardening-r2 | gate-hardening-r2 | infra | active |
| praxis-test-perf | test-perf-slicing | infra | active |
| praxis-coverage-wsl | coverage-wsl | infra | WSL judge coverage (AtomCode) |
| praxis-hooks-strict | hooks-strict | infra | strict commit-msg worktree enforcement |
| praxis-gate-hygiene | feature/opencode-gate-hygiene | infra | gate-review follow-ups (OpenCode/ox-alpha, user-pinned) |
| praxis-refactor | feature/system-refactor-phase1 | refactor | Phase 1: eliminate L1 transition shims and clean layer boundaries |

## Shared-file change log

| Date | File | Agent | Change | Status |
|---|---|---|---|---|

| 2026-08-22 | config/discovery/commits.yaml | OpenCode (l3-normalize) | registered `services` scope + scope_dirs entry (46-file dir had none; exposed by slice B1) | reconciled retro-registry |
| 2026-08-22 | scripts/sh/verify-completion.sh + judge-stats.sh + verify-local-merge.sh | AtomCode | judge test-skip visibility (skipped_tests record + dashboard + merge notice) | in judge-tests-gate (this commit) |
| 2026-08-22 | .githooks/commit-msg + Makefile + .githooks/commit-template.txt + .github/workflows/commit-lint.yml | OpenCode | strict commit-msg: enforce executable, absolute hooksPath, bypass audit, worktree CI gate | in hooks-strict (this commit) |
| 2026-08-22 | scripts/sh/ensure-hooks.sh + scripts/py/commit_strict.py + tests/infra/*hook* | OpenCode | worktree inheritance enforcer and strict hook tests | in hooks-strict (this commit) |
| 2026-08-22 | .githooks/commit-msg + scripts/sh/* + scripts/js/validate-commit.mjs + scripts/py/gen_commits_json.py + config/discovery/commits.json | AtomCode | test-suite hardening (must_include regression + judge/rotate tests) + set -euo + Node validator restore + commits.json regen | in opt-hardening (this commit) |
| 2026-08-22 | config/discovery/commits.yaml + commits.json + scripts/py/commit_scan.py + gen_commits_json.py + scripts/js/validate-commit.mjs + scripts/sh/* | AtomCode | single-source type-content rules + set-flag cleanup | in opt-hardening (this commit) |
| 2026-08-23 | scripts/py/audit_merge_hunks.py + tests/infra/test_merge_hunks.py + AGENTS.md + docs/workflow/* | GPT (root-kernel-next) | fail closed on sensitive-file deletions and multi-hunk full replacements; record incident regression | in feature/root-kernel-next |
| 2026-08-23 | crates/l1-kernel-rs/src/process_group.rs + crates/l1-kernel-rs/tests/process_group.rs + docs/architecture/* + docs/roadmaps/frontend-kernel-roadmap.md | GPT (root-kernel-next) | bounded reaper plan selection copies at most max_members handles per sweep; independent regression covers multi-group budget accounting | in feature/root-kernel-next |
| 2026-08-23 | crates/l1-kernel-rs/src/benchmark_runner.rs + crates/l1-kernel-rs/tests/benchmark_runner.rs + docs/architecture/l1-kernel.md + docs/roadmaps/frontend-kernel-roadmap.md | GPT (root-kernel-next) | process.group.reaper benchmark now forces 64-member multi-sweep progress so the bounded-selection optimization is measured | in feature/root-kernel-next |
| 2026-08-23 | crates/l1-kernel-rs/src/process_group.rs + benchmark_runner.rs + src/bin/rust-process-group-bench.rs + crates/l1-kernel-rs/tests/* + docs/architecture/* + docs/roadmaps/frontend-kernel-roadmap.md | GPT (root-kernel-next) | terminal-member counter, snapshot-free reaper fast path, isolated process.group.reaper v3 evidence | in feature/root-kernel-next |
| 2026-08-23 | docs/workflow/commits.md + tests/infra/test_config_consistency.py | GPT (root-kernel-next) | remove stale absent-generator claim and lock the checked-in JSON mirror contract | in feature/root-kernel-next |
| 2026-08-24 | scripts/sh/judge-stats.sh + docs/judge-stats.md | AtomCode | judge no-op filter: checks-all-zero runs excluded from runs/rate (dashboard no longer inflated by fully-skipped invocations) | in judge-stats-nop-filter (this commit) |
| 2026-08-23 | crates/l1-kernel-rs/src/registry_base.rs + benchmark_runner.rs + src/bin/rust-registry-base-bench.rs + crates/l1-kernel-rs/tests/* + docs/architecture/* + docs/roadmaps/frontend-kernel-roadmap.md + Makefile | GPT (root-kernel-next) | hash-index registry lookup with stable order semantics and isolated registry.base.lookup v3 evidence | in feature/root-kernel-next |
| 2026-08-23 | docs/roadmaps/l2-ts-rewrite-mapping.md | GPT (root-kernel-next) | carry forward the latest main-tree TS mapping document so the merge audit does not treat it as a deletion | in feature/root-kernel-next |
| 2026-08-23 | shared governance files and Rust kernel baseline | GPT (root-kernel-integration) | merge current kernel line on top of main while preserving mainline hook/config semantics | resolved in feature/root-kernel-integration |
| 2026-08-23 | scripts/sh/verify-local-merge.sh + scripts/py/audit_merge_hunks.py + tests/infra/test_merge_hunks.py | AtomCode | review-driven: guard hunk-audit against set -e (exit-code mapping), count `-`/`+`-prefixed body lines (whole-file guard bypass) | in feature/l2-finalize (this commit) |
| 2026-08-23 | scripts/py/commit_scan.py + tests/infra/test_commit_scan.py | AtomCode (originated) | commit-audit breakdown: scan_range_stats reports validated vs merge-skipped honestly | **absorbed into OpenCode 02a446a0 (feature/hooks-python-fallback)** — see clobber warning 2 |
| 2026-08-23 | crates/l1-kernel-rs/src/{snapshot,session,agent_loop,terminal,benchmark_runner}.rs + crates/l1-kernel-rs/src/bin/rust-session-snapshot-page-bench.rs + crates/l1-kernel-rs/tests/{snapshot_page,benchmark_runner}.rs + Makefile + docs/architecture/{l1-kernel,multilang-build}.md + docs/roadmaps/frontend-kernel-roadmap.md | GPT (root-l1-snapshot-boundary) | bounded max-heap book pages retain at most limit+1 handles; session reads use shard RwLocks; v3 page/read and session/write benchmarks record only blocked lock waits without timing public APIs | in feature/root-l1-snapshot-boundary |
| 2026-08-24 | crates/l1-kernel-rs/src/benchmark_runner.rs + crates/l1-kernel-rs/src/bin/rust-session-snapshot-page-contention-bench.rs + crates/l1-kernel-rs/tests/{snapshot_page,benchmark_runner}.rs + Makefile + docs/architecture/{l1-kernel,multilang-build}.md + docs/roadmaps/frontend-kernel-roadmap.md | GPT (root-l1-snapshot-boundary) | isolated single-shard page-read/write contention bundle; v3 lock-wait evidence shows 4-worker plateau and rising write interference; no runtime authority | in feature/root-l1-snapshot-boundary |
| 2026-08-24 | crates/l1-kernel-rs/src/{session,snapshot}.rs + crates/l1-kernel-rs/tests/snapshot_page.rs + docs/architecture/{l1-kernel,multilang-build}.md + docs/roadmaps/frontend-kernel-roadmap.md | GPT (root-l1-snapshot-boundary) | SessionBook shard ordered identity index bounds page traversal to limit+1; independent remove/restore regression; fixed-host A/B records material write tradeoff and mixed-bundle lock-wait reduction | in feature/root-l1-snapshot-boundary |
| 2026-08-24 | crates/l1-kernel-rs/src/{agent_loop,terminal,benchmark_runner}.rs + crates/l1-kernel-rs/src/bin/{rust-agent-loop-snapshot-page-bench,rust-terminal-snapshot-page-bench}.rs + crates/l1-kernel-rs/tests/{snapshot_page,benchmark_runner}.rs + Makefile + docs/architecture/{l1-kernel,multilang-build}.md + docs/roadmaps/frontend-kernel-roadmap.md | GPT (root-l1-snapshot-boundary) | AgentLoopBook and TerminalBook ordered identity indexes cover register/restore/page paths; benchmark-only try_read lock-wait probes now record real fallback time; fixed-host baselines remain read-only and tests stay in the independent Rust domain | in feature/root-l1-snapshot-boundary |
| 2026-08-24 | main 588202f L1/L2 communication line + snapshot boundary bundle | GPT (root-l1-snapshot-boundary) | rebased the snapshot/page performance slice onto the latest local main; preserved host dispatch, outbox, session identity/lifecycle, protocol, and their independent tests; only mechanical rustfmt changes touched main-owned communication files | in feature/root-l1-snapshot-aligned |
| 2026-08-25 | scripts/sh/verify-completion.sh + judge-stats.sh + docs/architecture/completion-judge.md | AtomCode | judge scorecard hardening: zero-value metric preservation, full-mode rate tracking, git exemption parsing (-z), flock concurrency, worktree log resolution | in feature/judge-stats-hardening (6c555c34) |
| 2026-08-25 | config/discovery/commits.yaml + commits.json + .githooks/commit-msg + scripts/py/commit_scan.py + detect_agent.py | Antigravity | anti-impersonation governance: probe runtime first, block random grabbing, Antigravity/Gemini registration, user escalation guidance | in feature/judge-stats-hardening (dd90dd62) |
| 2026-08-25 | scripts/py/commit_scan.py + scripts/js/validate-commit.mjs + tests/infra/test_commit_* | Antigravity | commit format hardening: imperative mood verb enforcement, strict EOF trailer sentinel, tests | in feature/judge-stats-hardening (1ae3a3b4) |
| 2026-08-25 | scripts/sh/handoff-rotate.sh + docs/agent-handoff/* | Antigravity | fix table row output order before ## Clobber warnings in rotation awk script, rotate threshold archive | in feature/judge-stats-hardening (716fa62d) |
| 2026-08-25 | scripts/sh/verify-completion.sh + tests/conftest.py + CHANGELOG.md | Antigravity | normalize conftest imports for ruff, bound WSL judge workers, refresh changelog | in feature/judge-stats-hardening (6f6d924f) |
| 2026-08-25 | scripts/sh/verify-main-merge-gate.sh | Antigravity | support user-granted MERGE_GATE_SKIP waiver with mandatory MERGE_GATE_REASON | in feature/judge-stats-hardening (this commit) |
| 2026-08-25 | config/discovery/commits.yaml + commits.json + scripts/py/gen_commits_json.py + commit_scan.py + scripts/js/validate-commit.mjs + tests/infra/test_commit_scan.py | OpenCode (ox-alpha) | single-source imperative verb list: `non_imperative_verbs` key in registry, mirror regenerated, py/mjs consume it (inline fallback only) | in feature/opencode-gate-hygiene (this commit) |
| 2026-08-25 | scripts/sh/verify-completion.sh + judge-stats.sh + tests/infra/test_judge_stats.py | OpenCode (ox-alpha) | waived net-delta honesty: MERGE_GATE_SKIP pass recorded as delta_waived=1, aggregated as delta_waived_runs (+ dashboard notice); drop dead XDIST_ARGS WSL branch | in feature/opencode-gate-hygiene (this commit) |
| 2026-08-25 | scripts/sh/verify-completion.sh + scripts/js/validate-commit.mjs + docs/architecture/completion-judge.md + tests/infra/test_commit_scan.py | AtomCode | gate hygiene: align complexity doc with impl (at most 12 >200-line funcs), Node validator single-source (fail closed on missing mirror keys), type_content_rules drift guard | in feature/atomcode-gate-prompt-hygiene (this commit) |
| 2026-08-25 | AGENTS.md + docs/contracts/kernel-contract.json + src/l1/* + src/l2/* + src/l3/* + src/l4/* | Antigravity (gemini-3.7-flash) | eliminate L1 transition shims (commands, model_registry, prompts), decouple L1 identity_binding via callback, reduce ALLOWLIST | in feature/system-refactor-phase1 (4ed1ecd3) |
| 2026-08-25 | docs/project-structure.md + src/l3/tools/* + src/l3/services/* + tests/fixtures/* | Antigravity (gemini-3.7-flash) | directory standardization: add tools package init, taxonomy docs, move test fixtures to tests/fixtures/cards/, remove scratch script | in feature/system-refactor-phase1 (3b09bb6b) |
| 2026-08-25 | src/l2/* + src/l3/services/* + src/l4/api_handlers/* + tests/infra/test_layer_imports.py | Antigravity (gemini-3.7-flash) | Phase 2: eliminate L2 shell command L4 imports via adapter_bridge and ModelService, enforce 0 L1 upward imports | in feature/system-refactor-phase1 (0f5db057) |
| 2026-08-26 | packages/protocol-ts/* + crates/l1-kernel-rs/* + src/l3/cell/peers/l3.py + tests/fixtures/* | Antigravity (gemini-3.7-flash) | Phase 3: align cross-language protocol v1 conformance across TypeScript, Rust, and Python, fix L3 CentralController imports | in feature/system-refactor-phase1 (this commit) |
| 2026-08-23 | config/discovery/commits.yaml | OpenCode (ox-alpha) | register rust scope (crates/) for L1L2 docking execution | active |
| 2026-08-25 | crates/l1-kernel-rs/tests/** + crates/l1-kernel-rs/Cargo.toml + tests/infra/test_rust_test_domain.py + Makefile + docs/architecture/* + docs/design/rust-first-kernel-rewrite.md + docs/roadmaps/frontend-kernel-roadmap.md + crates/README.md + tests/fixtures/protocol_v1_conformance.json | GPT (root-l1-runtime-perf) | normalize 88 Rust integration targets into 11 explicit test domains, preserve historical Cargo target names, add bounded domain runner and root-level test regression gate | in feature/root-l1-runtime-perf |
| 2026-08-25 | crates/l1-kernel-rs/src/input_activity.rs + crates/l1-kernel-rs/tests/terminal/input_activity.rs + crates/l1-kernel-rs/Cargo.toml + packages/protocol-ts/src/input-activity.ts + packages/protocol-ts/tests/input-activity.test.ts + tests/fixtures/kernel_input_activity_vectors.json + docs/architecture/{l1-kernel,multilang-build,llms-full}.txt + docs/design/rust-first-kernel-rewrite.md + docs/roadmaps/frontend-kernel-roadmap.md + crates/README.md | GPT (root-l1-runtime-perf) | freeze T4a aggregate input-activity value contract with Rust/TS shared vectors; keep hardware adapters, raw input, permission UX, and runtime authority host-owned | in feature/root-l1-runtime-perf |
| 2026-08-26 | config/discovery/commits.yaml + config/discovery/commits.json + docs/agent-handoff/ALIGNMENT.md | Codex (GPT5.6Terra) | register the user-pinned Codex author identity and model for verified commit attribution | in feature/root-l1-runtime-perf |
| 2026-08-26 | packages/protocol-ts/src/engine/transports/{line-transport,stdio,ws,ssh,rust-host,index}.ts + packages/protocol-ts/tests/{transports,host-transport,e2e.stdio,e2e.rust.stdio,three-way-vectors}.test.ts + docs/architecture/{l2-shell-engine,multilang-build}.md + docs/roadmaps/{l1-l2-docking,frontend-kernel-roadmap,README}.md + docs/design/l1l2-docking-execution-plan.md + CHANGELOG.md | Codex (GPT5.6Terra) | implement D2 TS↔Rust host docking: opt-in PRAXIS_RUST_HOST factory, UTF-8 frame bound, dual-host e2e, three-way canonical vectors, and roadmap sync | in feature/ts-rust-e2e-docking |
| 2026-08-26 | packages/protocol-ts/src/engine/transports/{line-transport,stdio,rust-host}.ts + packages/protocol-ts/tests/{transports,host-transport}.test.ts + docs/architecture/l2-shell-engine.md + docs/roadmaps/l1-l2-docking.md + docs/design/l1l2-docking-execution-plan.md + CHANGELOG.md | Codex (GPT5.6Terra) | fail pending TS requests immediately on child/input disconnect; validate transport budgets and keep reconnect explicit | in feature/ts-rust-e2e-docking |
| 2026-08-26 | packages/protocol-ts/src/engine/transports/line-transport.ts + packages/protocol-ts/tests/transports.test.ts + docs/roadmaps/l1-l2-docking.md + docs/design/l1l2-docking-execution-plan.md + CHANGELOG.md | Codex (GPT5.6Terra) | terminate on synthetic session-fault result without waiting for an ack | in feature/ts-rust-e2e-docking |
| 2026-08-26 | packages/protocol-ts/src/engine/bridge.ts + packages/protocol-ts/tests/bridge-domains.test.ts + docs/architecture/l2-shell-engine.md + docs/roadmaps/l1-l2-docking.md + CHANGELOG.md | Codex (GPT5.6Terra) | constrain TS sequence wraparound to safe integers and avoid unsafe increment | in feature/ts-rust-e2e-docking |
| 2026-08-26 | docs/design/l1l2-docking-execution-plan.md | Codex (GPT5.6Terra) | record partial D0.4 sequence-boundary closure in the construction plan | in feature/ts-rust-e2e-docking |
| 2026-08-26 | packages/protocol-ts/src/envelope.ts + packages/protocol-ts/tests/authority-guards.test.ts + docs/architecture/l2-shell-engine.md + docs/roadmaps/l1-l2-docking.md + CHANGELOG.md | Codex (GPT5.6Terra) | reject unsafe TS wire sequence integers to prevent JSON rounding; retain Rust u64 peer capability | in feature/ts-rust-e2e-docking |
| 2026-08-26 | crates/l1-kernel-rs/src/{protocol,host_dispatch}.rs + crates/l1-kernel-rs/tests/{protocol/protocol,runtime/host_dispatch}.rs + packages/protocol-ts/src/{types,envelope}.ts + packages/protocol-ts/src/engine/{bridge,session-manager}.ts + tests/fixtures/protocol_v1_conformance.json + src/l2/protocol/{envelope,host,schema}.py + docs/architecture/l2-shell-engine.md + docs/roadmaps/l1-l2-docking.md + CHANGELOG.md | Codex (GPT5.6Terra) | close D0.4 safe wire sequence boundary, target-session control routing, deduplicated recovery, and Rust/Python host event parity | in feature/ts-rust-e2e-docking |
| 2026-08-26 | packages/protocol-ts/src/engine/{session-checkpoint,session-manager}.ts + packages/protocol-ts/tests/session-checkpoint.test.ts + crates/l1-kernel-rs/tests/session/session_store.rs + tests/fixtures/kernel_session_store_document.json + docs/{architecture/l2-shell-engine.md,design/l1l2-docking-execution-plan.md,roadmaps/l1-l2-docking.md} | Codex (GPT5.6Terra) | add Rust session-store checkpoint codec, shared TS/Rust fixture, atomic TS adapter, and O(1) multiplexer deduplication | in feature/ts-rust-e2e-docking |
| 2026-08-26 | crates/l1-kernel-rs/src/bin/rust-session-store-probe.rs + crates/l1-kernel-rs/Cargo.toml + packages/protocol-ts/tests/session-store.e2e.test.ts + docs/{architecture/multilang-build.md,design/l1l2-docking-execution-plan.md,roadmaps/l1-l2-docking.md} | Codex (GPT5.6Terra) | add process-level G4 session-store mutual verification; probe remains test-only and candidate-only | in feature/ts-rust-e2e-docking |
| 2026-08-26 | packages/protocol-ts/src/engine/session-manager.ts + packages/protocol-ts/tests/session-manager.test.ts + docs/architecture/l2-shell-engine.md | Codex (GPT5.6Terra) | bound the non-authoritative TS event mirror and prune acknowledged prefixes before stalled-view eviction | in feature/ts-rust-e2e-docking |
| 2026-08-26 | crates/l1-kernel-rs/src/runtime.rs + crates/l1-kernel-rs/tests/runtime/runtime.rs + docs/architecture/l1-kernel.md + docs/design/rust-first-kernel-rewrite.md + docs/roadmaps/frontend-kernel-roadmap.md | Codex (GPT5.6Terra) | attach Rust-owned Session/Terminal/AgentLoop execution books to KernelRuntime with atomic clean checkpoint and explicit unclean recovery | in feature/ts-rust-e2e-docking |
| 2026-08-26 | crates/l1-kernel-rs/src/{recovery,lib,runtime}.rs + crates/l1-kernel-rs/tests/{storage/recovery,session/execution_store,runtime/runtime}.rs + crates/l1-kernel-rs/Cargo.toml + packages/protocol-ts/src/engine/execution-checkpoint.ts + packages/protocol-ts/tests/execution-checkpoint.test.ts + tests/fixtures/kernel_execution_store_document.json + docs/{architecture/l1-kernel.md,l2-shell-engine.md,multilang-build.md} + docs/design/rust-first-kernel-rewrite.md + docs/roadmaps/{frontend-kernel-roadmap.md,l1-l2-docking.md} | Codex (GPT5.6Terra) | add side-effect-free Rust recovery decision trigger and TS read-only execution checkpoint projection | in feature/ts-rust-e2e-docking |
| 2026-08-26 | crates/l1-kernel-rs/src/runtime.rs + crates/l1-kernel-rs/tests/runtime/runtime.rs + docs/{architecture/l1-kernel.md,design/rust-first-kernel-rewrite.md,roadmaps/frontend-kernel-roadmap.md} | Codex (GPT5.6Terra) | require exact-generation recovery acknowledgement before persistent runtime boot; reject stale or inconsistent roots | in feature/ts-rust-e2e-docking |
| 2026-08-26 | crates/l1-kernel-rs/src/preflight.rs + crates/l1-kernel-rs/src/bin/rust-kernel-preflight.rs + crates/l1-kernel-rs/tests/assembly/preflight.rs + crates/l1-kernel-rs/Cargo.toml + Makefile + crates/README.md + docs/{architecture/l1-kernel.md,multilang-build.md} + docs/design/rust-first-kernel-rewrite.md + docs/roadmaps/frontend-kernel-roadmap.md | Codex (GPT5.6Terra) | add read-only R4 entry preflight report and automation build target; keep host probing and production boot outside candidate | in feature/ts-rust-e2e-docking |

## Clobber warnings (do not repeat)

1. `verify-completion.sh` (2026-08-22): an infra merge overwrote an
   already-merged optimization. Before an infra/refactor merge touches a
   shared script, check `git log --oneline <file>` and rebase on existing
   optimization history instead of clobbering it.
2. `commit_scan.py` (2026-08-23): AtomCode's uncommitted review-driven fix
   (scan_range_stats breakdown) was swept into OpenCode's 02a446a0
   (feature/hooks-python-fallback) when that agent committed with an
   unclean main tree — the code landed under the wrong attribution.
   Before committing on main, `git status --short` first; if the tree is
   not clean, do NOT `git add -A` across unrelated working changes.
3. `.githooks/commit-msg` (2026-08-23): P2#1 scaffolding-audit hardening —
   custom merge messages (hand-authored body present) now enforce the
   72-char subject contract; pure git-generated single-line merges stay
   exempt. Registered in this commit per the shared-file gate.
4. `config/discovery/commits.yaml` (2026-08-23, OpenCode/ox-alpha):
   registered legacy scopes `l2-ts` / `l2-ts-rewrite` / `l2-ts-polish` —
   commits with these scopes exist in merged history (feature/l2-ts-rewrite
   11-commit wave + feature/l2-ts-polish rebuild); scan_range tests over
   real history failed on unregistered scopes. Per registry convention:
   legacy scopes kept so strict mode never rejects previously-merged
   commits. Registered in this commit per the shared-file gate.
5. `config/discovery/commits.json` (2026-08-23, OpenCode/ox-alpha):
   mirror regenerated via gen_commits_json.py after the legacy-scope
   addition above; Node-only mirror now matches canonical yaml.
   Registered per the shared-file gate.
> Repair note (2026-08-25, OpenCode/ox-alpha): the stray table row below
> warning 5 — `| 2026-08-23 | config/discovery/commits.yaml | OpenCode
> (ox-alpha) | register rust scope (crates/) for L1L2 docking execution |
> active |` — was a rotation-order artifact of the pre-fix handoff-rotate.sh
> awk (rows flushed at END landed after the Clobber section). The rust-scope
> registration itself is valid history; the row is preserved here verbatim
> and removed from the tail so the change-log table stays well-formed and
> grep-count/rotate accounting agrees.
