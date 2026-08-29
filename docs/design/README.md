# Design Library — Pointer Index

> **指针式归档库**：每个文档拥有唯一 `pointer`，活跃库与归档库通过指针互引。归档文件位于 `archive/`（`.gitignore`，仅主树磁盘+删除历史），指针对外可检索。

## 活跃设计 (Active) — 7 篇

| Pointer | File | Title | Date | Status |
|---------|------|-------|------|--------|
| `DESIGN-2026-08-27-001` | `ci-automation-design.md` | Praxis 自动化 CI 审查模块设计 v2（card-triggered CI review + 模块联动） | 2026-08-27 | active |
| `DESIGN-2026-08-27-002` | `code-format-design.md` | Code Auto-Format Module — Design | 2026-08-27 | active |
| `DESIGN-2026-08-27-003` | `error-bus-design.md` | ErrorLog Bus Architecture Design | 2026-08-27 | active |
| `DESIGN-2026-08-27-004` | `kernel-rewrite-readiness-package.md` | Kernel Rewrite Readiness Package | 2026-08-27 | active |
| `DESIGN-2026-08-27-005` | `l1l2-docking-execution-plan.md` | L1↔L2 对接执行计划（施工级） | 2026-08-27 | active |
| `DESIGN-2026-08-27-006` | `load-adaptive-pool-design.md` | Praxis 负载自适应线程池设计 | 2026-08-27 | active |
| `DESIGN-2026-08-29-007` | `rust-first-kernel-rewrite.md` | Rust-First Kernel Rewrite Decision | 2026-08-29 | active |

## 归档设计 (Archived) — 17 篇

| Pointer | File | Title | Date |
|---------|------|-------|------|
| `ARCH-DESIGN-2026-07-21-001` | `archive/2026-07-21_design_ui-design.md` | NOMOS Praxis — Non-Chat UI/UX Design | 2026-07-21 |
| `ARCH-DESIGN-2026-07-22-002` | `archive/2026-07-22_design_architecture-complete.md` | NOMOS Praxis Complete Architecture | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-003` | `archive/2026-07-22_design_architecture-design.md` | Praxis Complete Architecture — Agent OS Federalism | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-004` | `archive/2026-07-22_design_g5-gate-design.md` | G5 Gate Definition and Tool Mapping Audit | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-005` | `archive/2026-07-22_design_os-shell-design-nomosagent-review.md` | 🟢 NOMOSAgent Cross-Review of the Praxis Agent OS Shell Desig | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-006` | `archive/2026-07-22_design_os-shell-design.md` | Praxis Agent OS Shell — Complete Design Draft | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-007` | `archive/2026-07-22_design_quickstart.md` | NOMOS Praxis Quickstart Guide | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-008` | `archive/2026-07-22_design_related-work.md` | Related Work — Praxis as an Agent Mini-Nation | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-009` | `archive/2026-07-22_design_task-card-design.md` | Task Card UX Spec — Intent Card Creation Entry Design | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-010` | `archive/2026-07-22_design_ui-design-opencode-review.md` | 🔵 OpenCode Cross-Review of the Praxis UI Design | 2026-07-22 |
| `ARCH-DESIGN-2026-07-25-011` | `archive/2026-07-25_design_architecture-actual.md` | Praxis Agent OS — Technical Architecture | 2026-07-25 |
| `ARCH-DESIGN-2026-08-05-012` | `archive/2026-08-05_design_foundation-gaps-plan.md` | Praxis 地基缺口施工规划 | 2026-08-05 |
| `ARCH-DESIGN-2026-08-12-013` | `archive/2026-08-12_design_dedup-subagent-discussion.md` | Dedup proposal: subagent implementations + assembly/discussi | 2026-08-12 |
| `ARCH-DESIGN-2026-08-16-014` | `archive/2026-08-16_design_test-runner-slicing-plan.md` | Test Runner Slicing Plan — Full Analysis | 2026-08-16 |
| `ARCH-DESIGN-2026-08-22-015` | `archive/2026-08-22_design_rust-readiness-hardening-plan.md` | Rust-Readiness Hardening Plan — Python 侧封口（先于 Rust 重写） | 2026-08-22 |
| `ARCH-DESIGN-2026-08-27-016` | `archive/2026-08-27_design_l3a-compression-v2-migration.md` | L3A 上下文压缩子系统 v2 迁移计划（3.1 补充缺口） | 2026-08-27 |
| `ARCH-DESIGN-2026-08-27-017` | `archive/2026-08-27_design_system-bus-architecture.md` | SystemBus — 通用组件总线架构 | 2026-08-27 |

## 归档评审 (Archived Reviews) — 24 篇

| Pointer | File | Title | Date |
|---------|------|-------|------|
| `ARCH-REVIEW-2026-07-22-001` | `archive/reviews/2026-07-22_review_foundation-audit.md` | Praxis 地基审查报告 | 2026-07-22 |
| `ARCH-REVIEW-2026-07-29-002` | `archive/reviews/2026-07-29_review_fix-verification.md` | 修复对照验证报告（第 4 轮 — 全量修复完成） | 2026-07-29 |
| `ARCH-REVIEW-2026-07-30-003` | `archive/reviews/2026-07-30_review_bus-dataflow-review.md` | 总线数据流审查报告 | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-004` | `archive/reviews/2026-07-30_review_l1-code-review.md` | L1 层代码质量审查报告（含 L2/L4 横向对比） | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-005` | `archive/reviews/2026-07-30_review_l1-kernel-code-review.md` | L1 Kernel Layer — 代码审查报告 | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-006` | `archive/reviews/2026-07-30_review_l2-code-review-comparative.md` | L2 Shell 层 — 代码审查对照分析 | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-007` | `archive/reviews/2026-07-30_review_l2-code-review.md` | L2 层代码质量审查报告 | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-008` | `archive/reviews/2026-07-30_review_l3-cell-code-review.md` | L3 Cell Layer — 代码审查报告 | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-009` | `archive/reviews/2026-07-30_review_l3-quality-review.md` | L3 层代码质量审查报告（L3A 改造后） | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-010` | `archive/reviews/2026-07-30_review_l3a-deep-review.md` | L3A 深度代码审查报告 | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-011` | `archive/reviews/2026-07-30_review_l3a-refactor-review.md` | L3A 改造审查报告 | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-012` | `archive/reviews/2026-07-30_review_l4-api-gateway-review.md` | L4 API 网关审查报告 | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-013` | `archive/reviews/2026-07-30_review_l4-code-review-comparative.md` | L4 Bridge 层 — 代码审查对照分析 | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-014` | `archive/reviews/2026-07-30_review_l4-code-review.md` | L4 层代码质量审查报告 | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-015` | `archive/reviews/2026-07-30_review_l5-user-code-review.md` | L5 User Layer — 代码质量审查报告 | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-016` | `archive/reviews/2026-07-30_review_perf-review.md` | 性能审查报告（全层） | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-017` | `archive/reviews/2026-07-30_review_r4-archive-review.md` | R4 档案馆体系审查报告 | 2026-07-30 |
| `ARCH-REVIEW-2026-08-07-018` | `archive/reviews/2026-08-07_review_worktree-quality-review-2026-08-07.md` | Worktree Quality Review — 19 Test Failures Full Accounting | 2026-08-07 |
| `ARCH-REVIEW-2026-08-09-019` | `archive/reviews/2026-08-09_review_decouple-review.md` | Praxis 分层解耦审查报告（2026-08-09） | 2026-08-09 |
| `ARCH-REVIEW-2026-08-09-020` | `archive/reviews/2026-08-09_review_perf-review.md` | Praxis 性能优化审查报告（2026-08-09）— 双模式文件 | 2026-08-09 |
| `ARCH-REVIEW-2026-08-11-021` | `archive/reviews/2026-08-11_review_perf-review.md` | Praxis 性能优化审查报告（2026-08-11）— 并发公平性修复 + 观察项记录 | 2026-08-11 |
| `ARCH-REVIEW-2026-08-16-022` | `archive/reviews/2026-08-16_review_engineering-debug-review.md` | Engineering Debug Mode — Code Review (2026-08-16) | 2026-08-16 |
| `ARCH-REVIEW-2026-08-18-023` | `archive/reviews/2026-08-18_review_kernel-readiness-preflight.md` | Kernel Rewrite Readiness Preflight (2026-08-18) | 2026-08-18 |
| `ARCH-REVIEW-2026-08-18-024` | `archive/reviews/2026-08-18_review_rust-pilot-gate.md` | Rust Pilot Gate Decision Record (2026-08-18) | 2026-08-18 |

## 命名规范

- **活跃库** `docs/design/*.md`：`kebab-case.md`，无 `praxis-` 前缀（已统一：`ci-automation-design.md` 等），frontmatter 含 `pointer: DESIGN-YYYY-MM-DD-NNN`
- **归档库** `docs/design/archive/`：`YYYY-MM-DD_design_<kebab>.md`（设计）与 `YYYY-MM-DD_review_<kebab>.md`（评审），frontmatter 含 `pointer: ARCH-DESIGN-...` / `ARCH-REVIEW-...`
- **指针**为唯一检索键，`POINTERS.json` 为机器可读索引（`pointer -> file`），`README.md` 为人读索引

## 使用

- 检索：`jq '.[] | select(.pointer=="ARCH-DESIGN-2026-08-05-001")' docs/design/POINTERS.json`
- 恢复：`git log --all --diff-filter=D -- docs/design/<original>` 或 `git show <commit>:<path>`
- 新增归档：`git rm <file>` 后 `mv` 至 `archive/YYYY-MM-DD_design_<name>.md`，frontmatter 添加 `pointer`，并更新本索引与 `POINTERS.json`
