# 设计文档库 — 指针索引（题头打标 DSL v1.2）

> **档案基准 v1.2** | 全宗号-年度-保管期限-件号 | 指针 `pointer` 主键 | 归档库 `archive/`（`.gitignore`，磁盘+删除历史）

## 基准（GB/T 9705 + DA/T 18 满配）

| 全宗号 | 编码 | 活跃库 | 归档库 | 保管期限 |
|---|---|---|---|---|
| `DESIGN` | `001` | `docs/design/*.md` | `archive/001-design/2026/永久/` | 永久 |
| `REVIEW` | `002` | — | `archive/002-review/2026/长期/` | 长期(10年) |

**文档命名**：`档号_题名.md` 即 `DESIGN-2026-永久-012_地基缺口施工规划.md`（档号前置，题名原文）

**题头 15 字段**：`pointer/档号/全宗号/年度/保管期限/题名/责任者/形成时间/载体/密级/页数/归档人/审核人/归档时间/来源/关键词/摘要`

## DSL v1.2（SQLite + JSON 双索引）

```bash
# JSON (jq, 48 条 0.001ms, 10k 0.47ms)
jq '.[] | select(.pointer=="ARCH-DESIGN-2026-08-05-012")' docs/design/POINTERS.json
# SQLite (10k 索引 0.02ms, 哈希 0.004ms)
sqlite3 docs/design/POINTERS.db "SELECT * FROM pointers WHERE pointer='ARCH-DESIGN-2026-08-05-012'"
sqlite3 docs/design/POINTERS.db "SELECT pointer,题名 FROM pointers WHERE 全宗号='DESIGN' AND 年度='2026'"
sqlite3 docs/design/POINTERS.db "SELECT * FROM pointers WHERE 题名 LIKE '%CI%'"
# Python hash (O1)
python3 -c "import json; m={x['pointer']:x for x in json.load(open('docs/design/POINTERS.json'))}; print(m['ARCH-DESIGN-2026-08-05-012'])"
```

## 索引效率

| 方案 | 48 条 | 10k 条 | 100k 推演 | 适用 |
|---|---|---|---|---|
| `jq` 线性 | 0.0010ms | 0.47ms | 4.7ms | <1k |
| `hash` O1 | 0.0001ms | 0.0045ms | 0.005ms | 指针精确 |
| `SQLite` 索引 | 0.04ms | 0.02ms | 0.05ms | 组合/范围/FTS |

当前 48 条已 `hash` 天花板；10k+ 切 `SQLite` 仍 `<0.1ms`。

## 活跃设计 (Active) — 7 篇

| 指针 | 档号 | 题名 | 文件 |
|------|------|------|------|
| `DESIGN-2026-08-27-001` | `DESIGN-2026-永久-001` | Praxis 自动化 CI 审查模块设计 v2（card-t | `ci-automation-design.md` |
| `DESIGN-2026-08-27-002` | `DESIGN-2026-永久-002` | Code Auto-Format Module — Desi | `code-format-design.md` |
| `DESIGN-2026-08-27-003` | `DESIGN-2026-永久-003` | ErrorLog Bus Architecture Desi | `error-bus-design.md` |
| `DESIGN-2026-08-27-004` | `DESIGN-2026-永久-004` | Kernel Rewrite Readiness Packa | `kernel-rewrite-readiness-package.md` |
| `DESIGN-2026-08-27-005` | `DESIGN-2026-永久-005` | L1↔L2 对接执行计划（施工级） | `l1l2-docking-execution-plan.md` |
| `DESIGN-2026-08-27-006` | `DESIGN-2026-永久-006` | Praxis 负载自适应线程池设计 | `load-adaptive-pool-design.md` |
| `DESIGN-2026-08-29-007` | `DESIGN-2026-永久-007` | Rust-First Kernel Rewrite Deci | `rust-first-kernel-rewrite.md` |

## 归档设计 (DESIGN 001) — 17 篇

| 指针 | 档号 | 题名 | 文件 |
|------|------|------|------|
| `ARCH-DESIGN-2026-07-21-001` | `DESIGN-2026-永久-001` | NOMOS Praxis — Non-Chat UI/UX  | `archive/001-design/2026/永久/DESIGN-2026-永久-001_ui-design.md` |
| `ARCH-DESIGN-2026-07-22-002` | `DESIGN-2026-永久-002` | NOMOS Praxis Complete Architec | `archive/001-design/2026/永久/DESIGN-2026-永久-002_architecture-complete.md` |
| `ARCH-DESIGN-2026-07-22-003` | `DESIGN-2026-永久-003` | Praxis Complete Architecture — | `archive/001-design/2026/永久/DESIGN-2026-永久-003_architecture-design.md` |
| `ARCH-DESIGN-2026-07-22-004` | `DESIGN-2026-永久-004` | G5 Gate Definition and Tool Ma | `archive/001-design/2026/永久/DESIGN-2026-永久-004_g5-gate-design.md` |
| `ARCH-DESIGN-2026-07-22-005` | `DESIGN-2026-永久-005` | 🟢 NOMOSAgent Cross-Review of t | `archive/001-design/2026/永久/DESIGN-2026-永久-005_os-shell-design-nomosagent-review.md` |
| `ARCH-DESIGN-2026-07-22-006` | `DESIGN-2026-永久-006` | Praxis Agent OS Shell — Comple | `archive/001-design/2026/永久/DESIGN-2026-永久-006_os-shell-design.md` |
| `ARCH-DESIGN-2026-07-22-007` | `DESIGN-2026-永久-007` | NOMOS Praxis Quickstart Guide | `archive/001-design/2026/永久/DESIGN-2026-永久-007_quickstart.md` |
| `ARCH-DESIGN-2026-07-22-008` | `DESIGN-2026-永久-008` | Related Work — Praxis as an Ag | `archive/001-design/2026/永久/DESIGN-2026-永久-008_related-work.md` |
| `ARCH-DESIGN-2026-07-22-009` | `DESIGN-2026-永久-009` | Task Card UX Spec — Intent Car | `archive/001-design/2026/永久/DESIGN-2026-永久-009_task-card-design.md` |
| `ARCH-DESIGN-2026-07-22-010` | `DESIGN-2026-永久-010` | 🔵 OpenCode Cross-Review of the | `archive/001-design/2026/永久/DESIGN-2026-永久-010_ui-design-opencode-review.md` |
| `ARCH-DESIGN-2026-07-25-011` | `DESIGN-2026-永久-011` | Praxis Agent OS — Technical Ar | `archive/001-design/2026/永久/DESIGN-2026-永久-011_architecture-actual.md` |
| `ARCH-DESIGN-2026-08-05-012` | `DESIGN-2026-永久-012` | Praxis 地基缺口施工规划 | `archive/001-design/2026/永久/DESIGN-2026-永久-012_foundation-gaps-plan.md` |
| `ARCH-DESIGN-2026-08-12-013` | `DESIGN-2026-永久-013` | Dedup proposal: subagent imple | `archive/001-design/2026/永久/DESIGN-2026-永久-013_dedup-subagent-discussion.md` |
| `ARCH-DESIGN-2026-08-16-014` | `DESIGN-2026-永久-014` | Test Runner Slicing Plan — Ful | `archive/001-design/2026/永久/DESIGN-2026-永久-014_test-runner-slicing-plan.md` |
| `ARCH-DESIGN-2026-08-22-015` | `DESIGN-2026-永久-015` | Rust-Readiness Hardening Plan  | `archive/001-design/2026/永久/DESIGN-2026-永久-015_rust-readiness-hardening-plan.md` |
| `ARCH-DESIGN-2026-08-27-016` | `DESIGN-2026-永久-016` | L3A 上下文压缩子系统 v2 迁移计划（3.1 补充缺口） | `archive/001-design/2026/永久/DESIGN-2026-永久-016_l3a-compression-v2-migration.md` |
| `ARCH-DESIGN-2026-08-27-017` | `DESIGN-2026-永久-017` | SystemBus — 通用组件总线架构 | `archive/001-design/2026/永久/DESIGN-2026-永久-017_system-bus-architecture.md` |

## 归档评审 (REVIEW 002) — 24 篇

| 指针 | 档号 | 题名 | 文件 |
|------|------|------|------|
| `ARCH-REVIEW-2026-07-22-001` | `REVIEW-2026-长期-001` | Praxis 地基审查报告 | `archive/002-review/2026/长期/REVIEW-2026-长期-001_foundation-audit.md` |
| `ARCH-REVIEW-2026-07-29-002` | `REVIEW-2026-长期-002` | 修复对照验证报告（第 4 轮 — 全量修复完成） | `archive/002-review/2026/长期/REVIEW-2026-长期-002_fix-verification.md` |
| `ARCH-REVIEW-2026-07-30-003` | `REVIEW-2026-长期-003` | 总线数据流审查报告 | `archive/002-review/2026/长期/REVIEW-2026-长期-003_bus-dataflow-review.md` |
| `ARCH-REVIEW-2026-07-30-004` | `REVIEW-2026-长期-004` | L1 层代码质量审查报告（含 L2/L4 横向对比） | `archive/002-review/2026/长期/REVIEW-2026-长期-004_l1-code-review.md` |
| `ARCH-REVIEW-2026-07-30-005` | `REVIEW-2026-长期-005` | L1 Kernel Layer — 代码审查报告 | `archive/002-review/2026/长期/REVIEW-2026-长期-005_l1-kernel-code-review.md` |
| `ARCH-REVIEW-2026-07-30-006` | `REVIEW-2026-长期-006` | L2 Shell 层 — 代码审查对照分析 | `archive/002-review/2026/长期/REVIEW-2026-长期-006_l2-code-review-comparative.md` |
| `ARCH-REVIEW-2026-07-30-007` | `REVIEW-2026-长期-007` | L2 层代码质量审查报告 | `archive/002-review/2026/长期/REVIEW-2026-长期-007_l2-code-review.md` |
| `ARCH-REVIEW-2026-07-30-008` | `REVIEW-2026-长期-008` | L3 Cell Layer — 代码审查报告 | `archive/002-review/2026/长期/REVIEW-2026-长期-008_l3-cell-code-review.md` |
| `ARCH-REVIEW-2026-07-30-009` | `REVIEW-2026-长期-009` | L3 层代码质量审查报告（L3A 改造后） | `archive/002-review/2026/长期/REVIEW-2026-长期-009_l3-quality-review.md` |
| `ARCH-REVIEW-2026-07-30-010` | `REVIEW-2026-长期-010` | L3A 深度代码审查报告 | `archive/002-review/2026/长期/REVIEW-2026-长期-010_l3a-deep-review.md` |
| `ARCH-REVIEW-2026-07-30-011` | `REVIEW-2026-长期-011` | L3A 改造审查报告 | `archive/002-review/2026/长期/REVIEW-2026-长期-011_l3a-refactor-review.md` |
| `ARCH-REVIEW-2026-07-30-012` | `REVIEW-2026-长期-012` | L4 API 网关审查报告 | `archive/002-review/2026/长期/REVIEW-2026-长期-012_l4-api-gateway-review.md` |
| `ARCH-REVIEW-2026-07-30-013` | `REVIEW-2026-长期-013` | L4 Bridge 层 — 代码审查对照分析 | `archive/002-review/2026/长期/REVIEW-2026-长期-013_l4-code-review-comparative.md` |
| `ARCH-REVIEW-2026-07-30-014` | `REVIEW-2026-长期-014` | L4 层代码质量审查报告 | `archive/002-review/2026/长期/REVIEW-2026-长期-014_l4-code-review.md` |
| `ARCH-REVIEW-2026-07-30-015` | `REVIEW-2026-长期-015` | L5 User Layer — 代码质量审查报告 | `archive/002-review/2026/长期/REVIEW-2026-长期-015_l5-user-code-review.md` |
| `ARCH-REVIEW-2026-07-30-016` | `REVIEW-2026-长期-016` | 性能审查报告（全层） | `archive/002-review/2026/长期/REVIEW-2026-长期-016_perf-review.md` |
| `ARCH-REVIEW-2026-07-30-017` | `REVIEW-2026-长期-017` | R4 档案馆体系审查报告 | `archive/002-review/2026/长期/REVIEW-2026-长期-017_r4-archive-review.md` |
| `ARCH-REVIEW-2026-08-07-018` | `REVIEW-2026-长期-018` | Worktree Quality Review — 19 T | `archive/002-review/2026/长期/REVIEW-2026-长期-018_worktree-quality-review-2026-08-07.md` |
| `ARCH-REVIEW-2026-08-09-019` | `REVIEW-2026-长期-019` | Praxis 分层解耦审查报告（2026-08-09） | `archive/002-review/2026/长期/REVIEW-2026-长期-019_decouple-review.md` |
| `ARCH-REVIEW-2026-08-09-020` | `REVIEW-2026-长期-020` | Praxis 性能优化审查报告（2026-08-09）— 双 | `archive/002-review/2026/长期/REVIEW-2026-长期-020_perf-review.md` |
| `ARCH-REVIEW-2026-08-11-021` | `REVIEW-2026-长期-021` | Praxis 性能优化审查报告（2026-08-11）— 并 | `archive/002-review/2026/长期/REVIEW-2026-长期-021_perf-review.md` |
| `ARCH-REVIEW-2026-08-16-022` | `REVIEW-2026-长期-022` | Engineering Debug Mode — Code  | `archive/002-review/2026/长期/REVIEW-2026-长期-022_engineering-debug-review.md` |
| `ARCH-REVIEW-2026-08-18-023` | `REVIEW-2026-长期-023` | Kernel Rewrite Readiness Prefl | `archive/002-review/2026/长期/REVIEW-2026-长期-023_kernel-readiness-preflight.md` |
| `ARCH-REVIEW-2026-08-18-024` | `REVIEW-2026-长期-024` | Rust Pilot Gate Decision Recor | `archive/002-review/2026/长期/REVIEW-2026-长期-024_rust-pilot-gate.md` |

## 恢复

```bash
cat docs/design/archive/001-design/2026/永久/DESIGN-2026-永久-012_*.md
git log --all --diff-filter=D -- docs/design/foundation-gaps-plan.md
```
