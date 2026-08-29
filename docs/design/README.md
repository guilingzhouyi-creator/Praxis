# 设计文档库 — 指针索引（题头打标 DSL）

> **档案基准 v1.1** | 全宗号-年度-保管期限-件号 | 指针 `pointer` 主键 | 归档库 `archive/`（`.gitignore`，磁盘+删除历史） | 活跃库 `docs/design/`（tracked）

## 统一基准（中国档案馆题头打标 + 指针 DSL）

**文件夹归属（已校正）**：

| 全宗号 | 活跃库 | 归档库 | 保管期限 | 说明 |
|---|---|---|---|---|
| `DESIGN` | `docs/design/*.md` | `docs/design/archive/design/YYYY-MM/` | 永久 | 设计类 |
| `REVIEW` | — | `docs/design/archive/review/YYYY-MM/` | 长期 | 评审类 |
| `DECISION` | `docs/decisions/*.md` | （已移出设计归档，归属 `DECISION` 全宗） | 永久 | 决策类不归入 `DESIGN` |
| `ISSUE` | `docs/issues/*.md` | （同上） | 短期 |  |

**文档命名**：
- 活跃：`kebab-case.md`（无 `praxis-`，已统一 `ci-automation-design.md` 等）
- 归档设计：`YYYY-MM-DD_design_<kebab>.md` 于 `archive/design/YYYY-MM/`
- 归档评审：`YYYY-MM-DD_review_<kebab>.md` 于 `archive/review/YYYY-MM/`

**题头** frontmatter 含 `pointer/档号/全宗号/年度/保管期限/题名/责任者/形成时间/载体`（GB/T 9705），`POINTERS.json` 为 DSL 索引。

## DSL 查询

```bash
# 指针
jq '.[] | select(.pointer=="ARCH-DESIGN-2026-08-05-012")' docs/design/POINTERS.json
# 全宗+年度
jq '.[] | select(.["全宗号"]=="DESIGN" and .["年度"]=="2026")' docs/design/POINTERS.json
# 题名
jq '.[] | select(.["题名"] | contains("CI"))' docs/design/POINTERS.json
# 保管期限
jq '.[] | select(.["保管期限"]=="永久")' docs/design/POINTERS.json
```

## 活跃设计 (Active) — 7 篇

| 指针 | 档号 | 题名 | 形成时间 | 文件 |
|------|------|------|----------|------|
| `DESIGN-2026-08-27-001` | `DESIGN-2026-永久-001` | Praxis 自动化 CI 审查模块设计 v2（card-triggered C | `ci-automation-design.md` | 2026-08-29 |
| `DESIGN-2026-08-27-002` | `DESIGN-2026-永久-002` | Code Auto-Format Module — Design | `code-format-design.md` | 2026-08-29 |
| `DESIGN-2026-08-27-003` | `DESIGN-2026-永久-003` | ErrorLog Bus Architecture Design | `error-bus-design.md` | 2026-08-29 |
| `DESIGN-2026-08-27-004` | `DESIGN-2026-永久-004` | Kernel Rewrite Readiness Package | `kernel-rewrite-readiness-package.md` | 2026-08-29 |
| `DESIGN-2026-08-27-005` | `DESIGN-2026-永久-005` | L1↔L2 对接执行计划（施工级） | `l1l2-docking-execution-plan.md` | 2026-08-29 |
| `DESIGN-2026-08-27-006` | `DESIGN-2026-永久-006` | Praxis 负载自适应线程池设计 | `load-adaptive-pool-design.md` | 2026-08-29 |
| `DESIGN-2026-08-29-007` | `DESIGN-2026-永久-007` | Rust-First Kernel Rewrite Decision | `rust-first-kernel-rewrite.md` | 2026-08-29 |

## 归档设计 (Archived DESIGN) — 17 篇

| 指针 | 档号 | 题名 | 文件 | 形成时间 |
|------|------|------|------|----------|
| `ARCH-DESIGN-2026-07-21-001` | `DESIGN-2026-永久-001` | NOMOS Praxis — Non-Chat UI/UX Design | `archive/design/2026-07/2026-07-21_design_ui-design.md` | 2026-07-21 |
| `ARCH-DESIGN-2026-07-22-002` | `DESIGN-2026-永久-002` | NOMOS Praxis Complete Architecture | `archive/design/2026-07/2026-07-22_design_architecture-complete.md` | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-003` | `DESIGN-2026-永久-003` | Praxis Complete Architecture — Agent OS  | `archive/design/2026-07/2026-07-22_design_architecture-design.md` | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-004` | `DESIGN-2026-永久-004` | G5 Gate Definition and Tool Mapping Audi | `archive/design/2026-07/2026-07-22_design_g5-gate-design.md` | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-005` | `DESIGN-2026-永久-005` | 🟢 NOMOSAgent Cross-Review of the Praxis  | `archive/design/2026-07/2026-07-22_design_os-shell-design-nomosagent-review.md` | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-006` | `DESIGN-2026-永久-006` | Praxis Agent OS Shell — Complete Design  | `archive/design/2026-07/2026-07-22_design_os-shell-design.md` | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-007` | `DESIGN-2026-永久-007` | NOMOS Praxis Quickstart Guide | `archive/design/2026-07/2026-07-22_design_quickstart.md` | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-008` | `DESIGN-2026-永久-008` | Related Work — Praxis as an Agent Mini-N | `archive/design/2026-07/2026-07-22_design_related-work.md` | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-009` | `DESIGN-2026-永久-009` | Task Card UX Spec — Intent Card Creation | `archive/design/2026-07/2026-07-22_design_task-card-design.md` | 2026-07-22 |
| `ARCH-DESIGN-2026-07-22-010` | `DESIGN-2026-永久-010` | 🔵 OpenCode Cross-Review of the Praxis UI | `archive/design/2026-07/2026-07-22_design_ui-design-opencode-review.md` | 2026-07-22 |
| `ARCH-DESIGN-2026-07-25-011` | `DESIGN-2026-永久-011` | Praxis Agent OS — Technical Architecture | `archive/design/2026-07/2026-07-25_design_architecture-actual.md` | 2026-07-25 |
| `ARCH-DESIGN-2026-08-05-012` | `DESIGN-2026-永久-012` | Praxis 地基缺口施工规划 | `archive/design/2026-08/2026-08-05_design_foundation-gaps-plan.md` | 2026-08-05 |
| `ARCH-DESIGN-2026-08-12-013` | `DESIGN-2026-永久-013` | Dedup proposal: subagent implementations | `archive/design/2026-08/2026-08-12_design_dedup-subagent-discussion.md` | 2026-08-12 |
| `ARCH-DESIGN-2026-08-16-014` | `DESIGN-2026-永久-014` | Test Runner Slicing Plan — Full Analysis | `archive/design/2026-08/2026-08-16_design_test-runner-slicing-plan.md` | 2026-08-16 |
| `ARCH-DESIGN-2026-08-22-015` | `DESIGN-2026-永久-015` | Rust-Readiness Hardening Plan — Python 侧 | `archive/design/2026-08/2026-08-22_design_rust-readiness-hardening-plan.md` | 2026-08-22 |
| `ARCH-DESIGN-2026-08-27-016` | `DESIGN-2026-永久-016` | L3A 上下文压缩子系统 v2 迁移计划（3.1 补充缺口） | `archive/design/2026-08/2026-08-27_design_l3a-compression-v2-migration.md` | 2026-08-27 |
| `ARCH-DESIGN-2026-08-27-017` | `DESIGN-2026-永久-017` | SystemBus — 通用组件总线架构 | `archive/design/2026-08/2026-08-27_design_system-bus-architecture.md` | 2026-08-27 |

## 归档评审 (Archived REVIEW) — 24 篇

| 指针 | 档号 | 题名 | 文件 | 形成时间 |
|------|------|------|------|----------|
| `ARCH-REVIEW-2026-07-22-001` | `REVIEW-2026-长期-001` | Praxis 地基审查报告 | `archive/review/2026-07/2026-07-22_review_foundation-audit.md` | 2026-07-22 |
| `ARCH-REVIEW-2026-07-29-002` | `REVIEW-2026-长期-002` | 修复对照验证报告（第 4 轮 — 全量修复完成） | `archive/review/2026-07/2026-07-29_review_fix-verification.md` | 2026-07-29 |
| `ARCH-REVIEW-2026-07-30-003` | `REVIEW-2026-长期-003` | 总线数据流审查报告 | `archive/review/2026-07/2026-07-30_review_bus-dataflow-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-004` | `REVIEW-2026-长期-004` | L1 层代码质量审查报告（含 L2/L4 横向对比） | `archive/review/2026-07/2026-07-30_review_l1-code-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-005` | `REVIEW-2026-长期-005` | L1 Kernel Layer — 代码审查报告 | `archive/review/2026-07/2026-07-30_review_l1-kernel-code-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-006` | `REVIEW-2026-长期-006` | L2 Shell 层 — 代码审查对照分析 | `archive/review/2026-07/2026-07-30_review_l2-code-review-comparative.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-007` | `REVIEW-2026-长期-007` | L2 层代码质量审查报告 | `archive/review/2026-07/2026-07-30_review_l2-code-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-008` | `REVIEW-2026-长期-008` | L3 Cell Layer — 代码审查报告 | `archive/review/2026-07/2026-07-30_review_l3-cell-code-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-009` | `REVIEW-2026-长期-009` | L3 层代码质量审查报告（L3A 改造后） | `archive/review/2026-07/2026-07-30_review_l3-quality-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-010` | `REVIEW-2026-长期-010` | L3A 深度代码审查报告 | `archive/review/2026-07/2026-07-30_review_l3a-deep-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-011` | `REVIEW-2026-长期-011` | L3A 改造审查报告 | `archive/review/2026-07/2026-07-30_review_l3a-refactor-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-012` | `REVIEW-2026-长期-012` | L4 API 网关审查报告 | `archive/review/2026-07/2026-07-30_review_l4-api-gateway-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-013` | `REVIEW-2026-长期-013` | L4 Bridge 层 — 代码审查对照分析 | `archive/review/2026-07/2026-07-30_review_l4-code-review-comparative.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-014` | `REVIEW-2026-长期-014` | L4 层代码质量审查报告 | `archive/review/2026-07/2026-07-30_review_l4-code-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-015` | `REVIEW-2026-长期-015` | L5 User Layer — 代码质量审查报告 | `archive/review/2026-07/2026-07-30_review_l5-user-code-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-016` | `REVIEW-2026-长期-016` | 性能审查报告（全层） | `archive/review/2026-07/2026-07-30_review_perf-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-07-30-017` | `REVIEW-2026-长期-017` | R4 档案馆体系审查报告 | `archive/review/2026-07/2026-07-30_review_r4-archive-review.md` | 2026-07-30 |
| `ARCH-REVIEW-2026-08-07-018` | `REVIEW-2026-长期-018` | Worktree Quality Review — 19 Test Failur | `archive/review/2026-08/2026-08-07_review_worktree-quality-review-2026-08-07.md` | 2026-08-07 |
| `ARCH-REVIEW-2026-08-09-019` | `REVIEW-2026-长期-019` | Praxis 分层解耦审查报告（2026-08-09） | `archive/review/2026-08/2026-08-09_review_decouple-review.md` | 2026-08-09 |
| `ARCH-REVIEW-2026-08-09-020` | `REVIEW-2026-长期-020` | Praxis 性能优化审查报告（2026-08-09）— 双模式文件 | `archive/review/2026-08/2026-08-09_review_perf-review.md` | 2026-08-09 |
| `ARCH-REVIEW-2026-08-11-021` | `REVIEW-2026-长期-021` | Praxis 性能优化审查报告（2026-08-11）— 并发公平性修复 + 观 | `archive/review/2026-08/2026-08-11_review_perf-review.md` | 2026-08-11 |
| `ARCH-REVIEW-2026-08-16-022` | `REVIEW-2026-长期-022` | Engineering Debug Mode — Code Review (20 | `archive/review/2026-08/2026-08-16_review_engineering-debug-review.md` | 2026-08-16 |
| `ARCH-REVIEW-2026-08-18-023` | `REVIEW-2026-长期-023` | Kernel Rewrite Readiness Preflight (2026 | `archive/review/2026-08/2026-08-18_review_kernel-readiness-preflight.md` | 2026-08-18 |
| `ARCH-REVIEW-2026-08-18-024` | `REVIEW-2026-长期-024` | Rust Pilot Gate Decision Record (2026-08 | `archive/review/2026-08/2026-08-18_review_rust-pilot-gate.md` | 2026-08-18 |

## 规范

- **活跃** `docs/design/*.md`：`kebab-case.md`，`frontmatter: pointer/档号/全宗号/年度/保管期限/题名/责任者/形成时间/载体`
- **归档** `archive/design/YYYY-MM/` 与 `archive/review/YYYY-MM/`，`YYYY-MM-DD_<type>_<kebab>.md`
- **索引** `POINTERS.json` 机器读，`README.md` 人读，`archive/INDEX.md` 磁盘镜像（`archive/SPEC.md` 为基准）

## 恢复

```bash
git log --all --diff-filter=D -- docs/design/foundation-gaps-plan.md
cat docs/design/archive/design/2026-08/2026-08-05_design_foundation-gaps-plan.md
```
