# Changelog

本项目所有重要变更记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 文档

- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh snapshot before mainline merge
- **Docs**: add L2 shell engine architecture + multifrontend roadmap
- **Docs**: rust-readiness hardening — plan status, kernel surface boundary
- **Docs (docs)**: fix deps reference in commits.md
- **Docs (docs)**: extract AGENTS.md long sections into indexed docs
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh doc-stats and CHANGELOG for fidelity branch
- **Docs (memory)**: sync architecture docs for fidelity mechanisms
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh doc-stats after memory perf fix
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh llms-full.txt with completion-judge row
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: add completion-judge spec and register it in doc indexes
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh snapshot before mainline merge
- **Docs (stats)**: refresh judge dashboard
- **Docs**: regenerate CHANGELOG [Unreleased] block
- **Docs**: align project-structure command count to 51
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh snapshot before mainline merge
- **Docs**: regenerate llms.txt and align command counts after rebase
- **Docs**: add engineering-debug feature review
- **Docs**: fix doc pointers and counts; add top-level index
- **Docs (infra)**: expand 22 short docstrings past the detail floor
- **Docs (stats)**: refresh judge dashboard
- **Docs (docs)**: refresh candidate architecture indexes
- **Docs (memory)**: detail candidate storage seam
- **Docs (docs)**: refresh generated indexes
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh doc-stats + changelog after cleanup
- **Docs (infra)**: fill 111 missing public docstrings
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh snapshot before mainline merge
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (agents)**: define two gate waivers and sync hints
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (roadmaps)**: centralize roadmap documents under docs/roadmaps/
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh snapshot before mainline merge
- **Docs (stats)**: refresh judge dashboard
- **Docs (agents)**: add branch accumulation quality gate
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh snapshot before mainline merge
- **Docs (stats)**: refresh judge dashboard
- **Docs (agents)**: mandate main-tree venv for worktree test runs
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (readme)**: capability areas (memory/compression/prompt/session upgrades) + refresh stats snapshot
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh snapshot before mainline merge
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh snapshot before mainline merge
- **Docs (stats)**: refresh judge dashboard
- **Docs (memory)**: document two-layer compression pipeline (execution vs decision)
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh snapshot before mainline merge
- **Docs (agents)**: CompletionJudge verdict + rejection-behavior rules
- **Docs (stats)**: refresh judge dashboard
- **Docs (stats)**: refresh snapshot before mainline merge
- **Docs (agents)**: document direct local push to github mirror

### 变更

- **Chore**: format fs_adapter_vfs test and refresh changelog
- **Refactor (kernel)**: shrink kernel surface — ports, params, moves (WS5)
- **Test (infra)**: split runner into per-layer slices
- **Chore**: ignore atomcode runtime config
- **Test (infra)**: isolate durable capability fixtures
- **Test (memory)**: document candidate rewrite seam and boundaries
- **Test (infra)**: register ports.storage singleton reset
- **Refactor (infra)**: clear PLR0911 exemptions across 27 modules
- **Refactor (l3)**: convert l3a dispatch to dict dispatch table
- **Refactor (l2)**: split _cmd_memory into global-op dispatch table
- **Refactor (l3)**: split evolve_skill into pipeline helpers
- **Refactor (l3)**: split session prompt() into stage helpers
- **Refactor (l3)**: split session compress() into stage helpers
- **Refactor (l3)**: split dispatch into per-subcommand handlers
- **Refactor (l3)**: split _init_discovery into per-section registrars
- **Refactor (l3)**: split boot() into phased helpers
- **Refactor (l3)**: split _build_run_context into gated injector methods
- **Refactor (l3)**: split handle_think into cohesive helpers
- **Refactor (l2)**: split _cmd_skills into per-subcommand helpers
- **Chore**: remove Qwen2.5 defaults, align CLAUDE.md with AGENTS.md
- **Test (infra)**: cover commit-scan engine and judge-stats aggregator
- **Test (memory)**: cover compression sensitive-scan hits and guard-blocked fold
- **Test (memory)**: cover L2 memory command extensions (corpus/digest/offload/sensitive/guard)
- **Test (memory)**: cover memory-upgrade API handlers (corpus/digest/offload/sensitive/guard)
- **Ci (push-both)**: push-safety pre-check + three-way verification
- **Refactor (scripts)**: normalize module names to snake_case (AGENTS.md rule)
- **Ci (push-both)**: auto-refresh doc-stats + record judge run before main push
- **Ci (nightly)**: add judge-stats effectiveness report job
- **Refactor (tool-presentation)**: make the run_code framework language-agnostic
- **Ci (push-both)**: drop sync-PR fallback — local branches push directly
- **Refactor (tool-presentation)**: simplify cache internals and hot path
- **Ci (commit-msg)**: enforce exactly one well-formed Co-Authored-By trailer
- **Ci (opt)**: fix failing evaluate/pr-commit-lint, trim CodeQL to push-only
- **Ci (slim)**: drop redundant full-suite job and PR-triggered benchmark (#9)
- **Ci (slim)**: drop redundant full-suite job and PR-triggered benchmark
- **Chore (reset)**: update repo references after remote reset to Praxis

### 性能

- **Perf (tests)**: eliminate fixed-wait hotspots; CI matrix smoke
- **Perf (memory)**: interruptible thread shutdown via Event.wait
- **Perf (agent)**: event-driven pool, preview truncation, harness cache
- **Perf (memory)**: cache retrieval vectors, tag index, semantic concurrency
- **Perf (memory)**: decouple candidate journal writes
- **Perf (bench)**: fix L1 Amdahl evidence
- **Perf (memory)**: index and journal candidate ledger
- **Perf (generalize)**: P0-P2 performance + TS-portability (mtime throttle, ring index, atomic counters, single-pass verify gate, storage/lock ports)

### 新增

- **Feat (kernel)**: process FSM, audit persist, event schema, sched port
- **Feat (atomcode)**: mirror remaining skills, fix descriptions, fix mcp docs
- **Feat (atomcode)**: mirror opencode skill refresh
- **Feat (opencode)**: add five architecture skills and refresh three
- **Feat (kernel)**: add capability syscall seam and harden G2/harness
- **Feat (kernel)**: close execution and auth bypasses for rust rewrite
- **Feat (memory)**: operator plane for compaction/premise-guard/dedup
- **Feat (memory)**: hybrid compaction extractor, premise guard, inject dedup
- **Feat (llm)**: enable tool-result read-back and provider failover
- **Feat (judge)**: separate full/fast verdict modes in CompletionJudge
- **Feat (tool)**: add marker-gated engineering debug mode
- **Feat (infra)**: per-layer performance baseline scanner
- **Feat (infra)**: per-layer quality baseline scanner
- **Feat (kernel)**: adopt ProcessPort execution boundary
- **Feat (skill)**: gate evolution through candidates
- **Feat (ports)**: complete L1 port seams for Rust-rewrite readiness
- **Feat (ci)**: enforce subject length and body structure in commit-scan
- **Feat (ci)**: enforce commit-scan policy across all gates
- **Feat (audit)**: non-English residue scanner — full-CJK plane, strict non-ASCII, docstring + md coverage, CI gate
- **Feat (judge)**: extend judge dashboard with metrics, branch, duration and pair analytics
- **Feat (opencode)**: add completion-judge and net-delta-gate skills, dedupe
- **Feat (atomcode)**: sync skills with the updated OpenCode skill set
- **Feat (generalize)**: bidirectional generalization pipeline (session-JSON supply, layered skill libs, memory feedback, verify gate, ring promotion)
- **Feat (session)**: session-management system (dual identity, monitor, auto-reload, decision-layer JSON trio, history, loader)
- **Feat (prompts)**: unified layered system-prompt architecture (Cell/global libraries, versioning, bypass monitor)
- **Feat (memory)**: expose execution-layer context audit via API + L2
- **Feat (agent)**: per-Cell context audit across the execution layer
- **Feat (agent)**: per-entity context snapshot for precise context management
- **Feat (memory)**: correlate reference-channel memory events with refined records
- **Feat (memory)**: structured tool-result register (fast path) + teardown-scoped reclaim
- **Feat (memory)**: reclaim conversation-side caches at Cell teardown
- **Feat (opencode)**: align agent skills with AGENTS.md gates and CI policies
- **Feat (memory)**: domain-filtered R4 archive, RC linkage, corpus surface, conversation caches, five-level compression, guardrails
- **Feat (skills)**: align atomcode skills with AGENTS.md + CI gates (lean)
- **Feat (gate)**: three locks on the net-delta gate (comments/deletion/hygiene)
- **Feat (judge)**: extend CompletionJudge to 11 checks (6 new dimensions)
- **Feat (attack)**: attack-posture tool suite + tooling linkage gaps
- **Feat (judge)**: committed dashboard — auto-updated on every mainline merge
- **Feat (tool-presentation)**: assemble stable-prefix prompt for vendor KV caches
- **Feat (tool-presentation)**: write back successful run_code results to cache
- **Feat (tool-presentation)**: wire run_code SDK bindings to the tool pipeline
- **Feat (harness)**: expose code level via L2 harness command + i18n
- **Feat (harness)**: unify tool-usage control bar (two classes + control line)
- **Feat (judge)**: quantify CompletionJudge effectiveness (auto-log + stats)
- **Feat (judge)**: CompletionJudge — machine decides "done", not the agent
- **Feat (tool-presentation)**: enforce tools:code-only in the tool pipeline
- **Feat (tool-presentation)**: reclaim per-Cell run_code cache on Cell shutdown
- **Feat (tool-presentation)**: add Code Mode / PTC presentation layer
- **Feat**: baseline — fresh single-commit repository

### 修复

- **Fix (shell)**: skip rc-loading in interactive shells; bound judge workers
- **Fix (memory)**: drop orphan MEMORY_COMPACTION_LLM_TIMEOUT param
- **Fix (memory)**: comply with truncation constants and layer-import allowlist
- **Fix (judge)**: count only full-mode records as COMPLETE in stats
- **Fix (agent)**: harness cache must not re-cache during reset
- **Fix (tool-presentation)**: point docstring at centralized roadmap paths
- **Fix (scripts)**: count kebab-case command keys and normalize handler names
- **Fix (memory)**: snapshot persistence path during writes
- **Fix (kernel)**: harden transport shutdown and persistence status
- **Fix (l3)**: harden approval persistence paths
- **Fix (memory)**: serialize candidate skill lifecycle
- **Fix (kernel)**: serialize autosave lifecycle
- **Fix (memory)**: disable empty persistence paths
- **Fix (l3a)**: prevent session history lock reentry
- **Fix (bench)**: calculate nearest-rank latency percentiles
- **Fix (kernel)**: make identity-binding persistence concurrent
- **Fix (kernel)**: adapt shutdown callbacks for signals
- **Fix (kernel)**: declare mixin host contracts
- **Fix (shell)**: preserve read-only ci commands
- **Fix (memory)**: preserve candidate policy across boot
- **Fix (skill)**: enforce candidate lifecycle transitions
- **Fix (scripts)**: match docs(changelog) prefix in skip regex
- **Fix (scripts)**: skip docs(changelog) commits in changelog scan
- **Fix (l3a)**: adapt _DISPATCHERS to heterogeneous handler signatures
- **Fix (ports)**: complete handles on rejection, translate OSError
- **Fix (tests)**: register new singleton resets in conftest _RESETS (CI full-run pollution)
- **Fix (judge)**: correct scan-singletons script name in CompletionJudge
- **Fix (session)**: wire 3.3 management into production runs + full terminal reset + docs
- **Fix (api)**: wire memory handlers + guard switch parsing + digest scan (review findings)
- **Fix (prompts)**: wire prompt architecture end-to-end (review gaps)
- **Fix (tool-presentation)**: replace SIGALRM timeout with worker-thread join; sync docs
- **Fix (test)**: align githooks COAUTH fixture

## [0.4.1] - 2026-08-07

代号 "Aether"。契约版本化治理落地(API v2 前缀统一、端点 manifest 为唯一事实源),
性能优化与跨层基础设施扩展。

### 新增
- **CI 审查模块**:card 触发的 CI 审查守护进程、ErrorBus 错误捕获与结构化错误响应、
  管道加固(门禁匹配器、AutoTest 缓存、rerun、webhook)、每 cell/agent 作用域的控制平面
- **技能系统**:内置技能目录泛化至 18 个技能、受众路由(按领域动态供给)、
  Matt-Pocock 式调用模型(disable-model-invocation)、技能演化(Lean 用例自动泛化、
  SKILL.md 持久化、Cell 绑定、R4/R5 关联)、内置技能只读 + 宪法门禁 + 默认会话激活
- **LSP 工具面**:server-backed definition/references 握手、5 个可用 LSP 工具、
  代码自动格式化模块(format_file/format_project + 写入路径钩子)
- **L3A 会话系统**:agents-md 项目手册管道(AGENTS.md)、语言无关客户端契约、
  user_id 接入会话提示与 cardwrite
- **模型/推理**:按 provider 的 reasoning effort 分层归一化、xhigh/max 推理档位、
  scout 与 L3A 子代理按任务切换策略、策略包运行时切换、模型规格概览 + caps API
- **基础设施端口**:auth/websocket/rpc/fs 端口抽象、RPC server + FilesystemPort 适配器、
  事件链与 hook 发射、双通道网关认证、启动预热、ws 端口契约
- **运行时空档模式**:governed/semi/minimal 门禁矩阵、harness 模式运行时切换(API + L2 Shell)
- **图数据库边**:edge_mode 控制 API + 端点 manifest 分类
- **其他**:用户画像侧信道(typed per-user model)、系统提示注入开关、
  自动测试门(卡片后后台测试回归 + 卡片反馈)

### 修复
- 非 daemon 线程挂起与终端卡片执行链
- `_UNLIMITED` NameError(steps-exhausted 路径)+ UTF-8 BOM 清理
- 内置技能契约测试、Lean 用例技能持久化到 SKILL.md
- 门禁链 G5 停滞回调(L1 不再导入 L3)、重复/未接线端口常量清理
- API 网关 `{param}` 匹配 + 尾斜杠劫持、query 参数不可覆盖路径资源 id、
  SSE v2 路径同步、7 工作域分类
- i18n 未知 /lang 回退 'en'、deepseek 默认 API URL 修正
- CI 门禁修复(lint、pre-commit、全量套件、Windows L1)、pytest-mock 加入 test extras、
  L2 shell 单例按测试重置(并行顺序污染)
- ReferenceChannel flusher 线程停止 + 按测试路径隔离、构建检测器测试隔离

### 性能
- 移除 token-store 泄漏、防抖 checkpoint 持久化、HTTP 连接池

### 文档
- 架构文档同步(并行协作门禁强化、契约版本化、分支/协作工作流)
- 技能系统架构、配置总览、SOC 引用更新

## [0.4.0] - 2026-07

首个契约里程碑版本。五层架构(L1 kernel → L5 user CLI)成型,Agent OS 核心可引导运行。

> 注:0.4.0 之前的变更历史待补充(仓库早期迭代未记录 changelog)。
