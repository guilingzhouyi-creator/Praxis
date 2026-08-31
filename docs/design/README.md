# Design Library — Pointer Index (Header DSL v1.3)

> **Archive Baseline v1.3** | English header to avoid ambiguity | `pointer` primary key

## Header (15 fields, English)

`pointer/archive_number/fonds/year/retention/title/author/formation_date/carrier/classification/pages/archivist/reviewer/archive_date/source/keywords/abstract`

- `abstract` is now distinct from `title` (generated from first paragraph, not duplicated)

## Active (5)

| pointer | archive_number | title | abstract | file |
|---------|----------------|-------|----------|------|
| `DESIGN-2026-08-31-110` | `DESIGN-2026-永久-110` | "TS L3 AgentLoop and Cell Coordination Slice" | Define the bounded TypeScript L3 AgentLoop and Cell coordination domains for the clean-break rewrite. | `l3-agent-loop-cell-plan.md` |
| `DESIGN-2026-08-31-109` | `DESIGN-2026-永久-109` | "TS L3 Card and Scheduler Coordination Slice" | Define the first clean-break TypeScript L3 Card and Scheduler data-only coordination seams. | `l3-card-scheduler-coordination-plan.md` |
| `DESIGN-2026-08-27-004` | `DESIGN-2026-永久-104` | "Kernel Rewrite Readiness Pack | Rust is the approved direction for a cle | `kernel-rewrite-readiness-package.md` |
| `DESIGN-2026-08-29-007` | `DESIGN-2026-永久-107` | "Rust-First Kernel Rewrite Dec | The future Praxis kernel is a clean-brea | `rust-first-kernel-rewrite.md` |
| `DESIGN-2026-08-29-108` | `DESIGN-2026-permanent-108` | "Edge Case Test | This is an automated end-to-end test for the pre-storage gate | `edge-case-test.md` |

## Archived DESIGN (001) — 22

| pointer | archive_number | title | abstract | file |
|---------|----------------|-------|----------|------|
| `ARCH-DESIGN-2026-08-29-018` | `DESIGN-2026-永久-018` | "Praxis 自动化 CI 审查模块设计 v2（card- | 为什么放 L4 而不是 L3：层导入约束（L3 → L2/L1，L3 不得 im | `archive/001-design/2026/永久/DESIGN-2026-永久-018_ci-automation-design.md` |
| `ARCH-DESIGN-2026-08-29-019` | `DESIGN-2026-永久-019` | "Code Auto-Format Module — Des | Peer Agents inside a Cell (mainly AgentL | `archive/001-design/2026/永久/DESIGN-2026-永久-019_code-format-design.md` |
| `ARCH-DESIGN-2026-08-29-020` | `DESIGN-2026-永久-020` | "ErrorLog Bus Architecture Des | Merge ~190 scattered exception capture p | `archive/001-design/2026/永久/DESIGN-2026-永久-020_error-bus-design.md` |
| `ARCH-DESIGN-2026-08-29-021` | `DESIGN-2026-永久-021` | "L1↔L2 对接执行计划（施工级）" | main ──┬─→ feature/l1l2-integration（集成分 | `archive/001-design/2026/永久/DESIGN-2026-永久-021_l1l2-docking-execution-plan.md` |
| `ARCH-DESIGN-2026-08-29-022` | `DESIGN-2026-永久-022` | "Praxis 负载自适应线程池设计" | `ThreadPoolWorker`（`systems/python-refer | `archive/001-design/2026/永久/DESIGN-2026-永久-022_load-adaptive-pool-design.md` |
| `ARCH-DESIGN-2026-07-21-001` | `DESIGN-2026-永久-001` | NOMOS Praxis — Non-Chat UI/UX  | Negate the premises of Chat UI, establis | `archive/001-design/2026/永久/DESIGN-2026-永久-001_ui-design.md` |
| `ARCH-DESIGN-2026-07-22-002` | `DESIGN-2026-永久-002` | NOMOS Praxis Complete Architec | Define Praxis as the Agent OS Desktop Sh | `archive/001-design/2026/永久/DESIGN-2026-永久-002_architecture-complete.md` |
| `ARCH-DESIGN-2026-07-22-003` | `DESIGN-2026-永久-003` | Praxis Complete Architecture — | Define the conceptual system of Agent OS | `archive/001-design/2026/永久/DESIGN-2026-永久-003_architecture-design.md` |
| `ARCH-DESIGN-2026-07-22-004` | `DESIGN-2026-永久-004` | G5 Gate Definition + Tool Mapp | G5 Gate Definition and Tool Mapping Audi | `archive/001-design/2026/永久/DESIGN-2026-永久-004_g5-gate-design.md` |
| `ARCH-DESIGN-2026-07-22-005` | `DESIGN-2026-永久-005` | 🟢 NOMOSAgent Cross-Review of t | The review confirms that the Agent OS Sh | `archive/001-design/2026/永久/DESIGN-2026-永久-005_os-shell-design-nomosagent-review.md` |
| `ARCH-DESIGN-2026-07-22-006` | `DESIGN-2026-永久-006` | Praxis Agent OS Shell — Comple | Define Praxis five-region desktop layout | `archive/001-design/2026/永久/DESIGN-2026-永久-006_os-shell-design.md` |
| `ARCH-DESIGN-2026-07-22-007` | `DESIGN-2026-永久-007` | NOMOS Praxis Quickstart Guide | - This repository is cloned locally | `archive/001-design/2026/永久/DESIGN-2026-永久-007_quickstart.md` |
| `ARCH-DESIGN-2026-07-22-008` | `DESIGN-2026-永久-008` | "Related Work — Praxis as an A | Status: baseline research for the organi | `archive/001-design/2026/永久/DESIGN-2026-永久-008_related-work.md` |
| `ARCH-DESIGN-2026-07-22-009` | `DESIGN-2026-永久-009` | Task Card UX Spec | Task Card UX Spec — Intent Card Creation | `archive/001-design/2026/永久/DESIGN-2026-永久-009_task-card-design.md` |
| `ARCH-DESIGN-2026-07-22-010` | `DESIGN-2026-永久-010` | 🔵 OpenCode Cross-Review of the | The review confirms that the three iron  | `archive/001-design/2026/永久/DESIGN-2026-永久-010_ui-design-opencode-review.md` |
| `ARCH-DESIGN-2026-07-25-011` | `DESIGN-2026-永久-011` | "Praxis Agent OS — Technical A | Praxis Agent OS maps to traditional comp | `archive/001-design/2026/永久/DESIGN-2026-永久-011_architecture-actual.md` |
| `ARCH-DESIGN-2026-08-05-012` | `DESIGN-2026-永久-012` | "Praxis 地基缺口施工规划" | 1. 每个阶段独立 `feature/foundation-*` 分支，双绿合并 | `archive/001-design/2026/永久/DESIGN-2026-永久-012_foundation-gaps-plan.md` |
| `ARCH-DESIGN-2026-08-12-013` | `DESIGN-2026-永久-013` | "Dedup proposal: subagent impl | Status: reviewed (2026-08-12). Audit + f | `archive/001-design/2026/永久/DESIGN-2026-永久-013_dedup-subagent-discussion.md` |
| `ARCH-DESIGN-2026-08-16-014` | `DESIGN-2026-永久-014` | "Test Runner Slicing Plan — Fu | 注：`tests/l4/llm` 实测 `rc=5`（失败，游离于 runner | `archive/001-design/2026/永久/DESIGN-2026-永久-014_test-runner-slicing-plan.md` |
| `ARCH-DESIGN-2026-08-22-015` | `DESIGN-2026-永久-015` | "Rust-Readiness Hardening Plan | 目标：在不切换语言的前提下，把当前 Kernel 变成"机制唯一、执行单门、授权 | `archive/001-design/2026/永久/DESIGN-2026-永久-015_rust-readiness-hardening-plan.md` |
| `ARCH-DESIGN-2026-08-27-016` | `DESIGN-2026-永久-016` | "L3A 上下文压缩子系统 v2 迁移计划（3.1 补充缺口 | - HEAD：`1a396e650f5cd5f21e9047c4a2e073ff | `archive/001-design/2026/永久/DESIGN-2026-永久-016_l3a-compression-v2-migration.md` |
| `ARCH-DESIGN-2026-08-27-017` | `DESIGN-2026-永久-017` | "SystemBus — 通用组件总线架构" | 当前 Praxis 组件间的关系是"手工串联"： | `archive/001-design/2026/永久/DESIGN-2026-永久-017_system-bus-architecture.md` |

## Archived REVIEW (002) — 24
| `ARCH-REVIEW-2026-07-22-001` | `REVIEW-2026-长期-001` | "Praxis 地基审查报告" | `archive/002-review/2026/长期/REVIEW-2026-长期-001_foundation-audit.md` |
| `ARCH-REVIEW-2026-07-29-002` | `REVIEW-2026-长期-002` | "修复对照验证报告（第 4 轮 — 全量修复完成）" | `archive/002-review/2026/长期/REVIEW-2026-长期-002_fix-verification.md` |
| `ARCH-REVIEW-2026-07-30-003` | `REVIEW-2026-长期-003` | "总线数据流审查报告" | `archive/002-review/2026/长期/REVIEW-2026-长期-003_bus-dataflow-review.md` |
| `ARCH-REVIEW-2026-07-30-004` | `REVIEW-2026-长期-004` | "L1 层代码质量审查报告（含 L2/L4 横向对比）" | `archive/002-review/2026/长期/REVIEW-2026-长期-004_l1-code-review.md` |
| `ARCH-REVIEW-2026-07-30-005` | `REVIEW-2026-长期-005` | "L1 Kernel Layer — 代码审查报告" | `archive/002-review/2026/长期/REVIEW-2026-长期-005_l1-kernel-code-review.md` |
| `ARCH-REVIEW-2026-07-30-006` | `REVIEW-2026-长期-006` | "L2 Shell 层 — 代码审查对照分析" | `archive/002-review/2026/长期/REVIEW-2026-长期-006_l2-code-review-comparative.md` |
| `ARCH-REVIEW-2026-07-30-007` | `REVIEW-2026-长期-007` | "L2 层代码质量审查报告" | `archive/002-review/2026/长期/REVIEW-2026-长期-007_l2-code-review.md` |
| `ARCH-REVIEW-2026-07-30-008` | `REVIEW-2026-长期-008` | "L3 Cell Layer — 代码审查报告" | `archive/002-review/2026/长期/REVIEW-2026-长期-008_l3-cell-code-review.md` |
| `ARCH-REVIEW-2026-07-30-009` | `REVIEW-2026-长期-009` | "L3 层代码质量审查报告（L3A 改造后）" | `archive/002-review/2026/长期/REVIEW-2026-长期-009_l3-quality-review.md` |
| `ARCH-REVIEW-2026-07-30-010` | `REVIEW-2026-长期-010` | "L3A 深度代码审查报告" | `archive/002-review/2026/长期/REVIEW-2026-长期-010_l3a-deep-review.md` |
| `ARCH-REVIEW-2026-07-30-011` | `REVIEW-2026-长期-011` | "L3A 改造审查报告" | `archive/002-review/2026/长期/REVIEW-2026-长期-011_l3a-refactor-review.md` |
| `ARCH-REVIEW-2026-07-30-012` | `REVIEW-2026-长期-012` | "L4 API 网关审查报告" | `archive/002-review/2026/长期/REVIEW-2026-长期-012_l4-api-gateway-review.md` |
| `ARCH-REVIEW-2026-07-30-013` | `REVIEW-2026-长期-013` | "L4 Bridge 层 — 代码审查对照分析" | `archive/002-review/2026/长期/REVIEW-2026-长期-013_l4-code-review-comparative.md` |
| `ARCH-REVIEW-2026-07-30-014` | `REVIEW-2026-长期-014` | "L4 层代码质量审查报告" | `archive/002-review/2026/长期/REVIEW-2026-长期-014_l4-code-review.md` |
| `ARCH-REVIEW-2026-07-30-015` | `REVIEW-2026-长期-015` | "L5 User Layer — 代码质量审查报告" | `archive/002-review/2026/长期/REVIEW-2026-长期-015_l5-user-code-review.md` |
| `ARCH-REVIEW-2026-07-30-016` | `REVIEW-2026-长期-016` | "性能审查报告（全层）" | `archive/002-review/2026/长期/REVIEW-2026-长期-016_perf-review.md` |
| `ARCH-REVIEW-2026-07-30-017` | `REVIEW-2026-长期-017` | "R4 档案馆体系审查报告" | `archive/002-review/2026/长期/REVIEW-2026-长期-017_r4-archive-review.md` |
| `ARCH-REVIEW-2026-08-07-018` | `REVIEW-2026-长期-018` | "Worktree Quality Review — 19  | `archive/002-review/2026/长期/REVIEW-2026-长期-018_worktree-quality-review-2026-08-07.md` |
| `ARCH-REVIEW-2026-08-09-019` | `REVIEW-2026-长期-019` | "Praxis 分层解耦审查报告（2026-08-09）" | `archive/002-review/2026/长期/REVIEW-2026-长期-019_decouple-review.md` |
| `ARCH-REVIEW-2026-08-09-020` | `REVIEW-2026-长期-020` | "Praxis 性能优化审查报告（2026-08-09）—  | `archive/002-review/2026/长期/REVIEW-2026-长期-020_perf-review.md` |
| `ARCH-REVIEW-2026-08-11-021` | `REVIEW-2026-长期-021` | "Praxis 性能优化审查报告（2026-08-11）—  | `archive/002-review/2026/长期/REVIEW-2026-长期-021_perf-review.md` |
| `ARCH-REVIEW-2026-08-16-022` | `REVIEW-2026-长期-022` | "Engineering Debug Mode — Code | `archive/002-review/2026/长期/REVIEW-2026-长期-022_engineering-debug-review.md` |
| `ARCH-REVIEW-2026-08-18-023` | `REVIEW-2026-长期-023` | "Kernel Rewrite Readiness Pref | `archive/002-review/2026/长期/REVIEW-2026-长期-023_kernel-readiness-preflight.md` |
| `ARCH-REVIEW-2026-08-18-024` | `REVIEW-2026-长期-024` | "Rust Pilot Gate Decision Reco | `archive/002-review/2026/长期/REVIEW-2026-长期-024_rust-pilot-gate.md` |
