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
| 2026-08-25 | src/l2/* + src/l3/services/* + src/l4/api_handlers/* + tests/infra/test_layer_imports.py | Antigravity (gemini-3.7-flash) | Phase 2: eliminate L2 shell command L4 imports via adapter_bridge and ModelService, enforce 0 L1 upward imports | in feature/system-refactor-phase1 (this commit) |
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
