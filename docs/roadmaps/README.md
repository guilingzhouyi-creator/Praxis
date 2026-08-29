# Praxis Roadmaps — 集中路线图索引

Praxis 的路线图文档集中于此目录统一管理。每条路线图登记其状态、阶段与
关联文档;实施文档与架构参考保留在原层目录,但在此登记索引。

| Roadmap | 状态 | 内容 | 关联 |
|---|---|---|---|
| [frontend-kernel-roadmap.md](frontend-kernel-roadmap.md) | 进行中(G4 自动化外围闭合;G5 Rust/TS 迁移脚手架启动;Rust-first 按 R0–R5/M1–M4 推进) | 前端矩阵(TUI/桌端/Web)+ Rust 下沉 L1 内核;M1 三端点已接通 | `docs/roadmaps/multilang-migration.md`、`docs/architecture/l5-user.md`、`docs/architecture/l2-shell.md`、`docs/roadmaps/production-closure-roadmap.md` |
| [production-closure-roadmap.md](production-closure-roadmap.md) | 规划(盲区全景;P0 会话面施工权威在 agent-os-3x-closure——其 Slice A–E 已合入 main,P0.5–P0.8 未实施) | 生产闭环、安全与可运维性:P0 会话/恢复/持久化/剩余旁路,P1 审计/VFS/身份/备份/可观测性/LLM/cron/schema,P2 治理收敛 | `docs/roadmaps/kernel-boundary-audit.md`、`docs/roadmaps/l2-multifrontend-session-layer.md`、`docs/roadmaps/frontend-kernel-roadmap.md`、`docs/architecture/security-evidence.md`、`docs/architecture/l3-memory.md` |
| [research-generalization.md](research-generalization.md) | 前瞻规划(Not Started) | 科研场景泛化:explorer 角色、假设管理、阴性知识库 | `docs/architecture/l3-memory.md`(R5 图) |
| [multilang-migration.md](multilang-migration.md) | 进行中(Python3 后端已交付,TS/Rust 槽位) | run_code / Code Mode (PTC) 多语言后端转换路径 | `docs/roadmaps/frontend-kernel-roadmap.md`、`docs/architecture/l3-tool-presentation.md` |
| [kernel-boundary-audit.md](kernel-boundary-audit.md) | 进行中(审计基线定稿;§11.2 Phase 0/1 封口与 Phase 2 候选切片已实施;B4/B6/B8/B9 与 G3/G6 待闭环) | L1 Kernel 边界审查——Rust 重写前置基线(评分 42/100;绕过路径/缺失不变量/最小内核/落地顺序) | `docs/roadmaps/frontend-kernel-roadmap.md`、`docs/roadmaps/multilang-migration.md`、`docs/architecture/l1-kernel.md`、`docs/design/kernel-rewrite-readiness-package.md` |
| [l2-multifrontend-session-layer.md](l2-multifrontend-session-layer.md) | 进行中(第三态:P0 单门与 P3 TS 引擎+三批/P4 扩展在 main;P1 桥/注入守卫与 P2 projection/web 接线被 edc5caa6 移除后未回补) | L2 Shell Engine 边界审计(评分 36/100)+ 多前端(Web/TUI/桌端/IDE/移动SSH)统一会话数据层协议 v1 + TS 重写路径(P0–P4) | `docs/architecture/l2-shell-engine.md`、`docs/roadmaps/kernel-boundary-audit.md`、`docs/roadmaps/frontend-kernel-roadmap.md`、`docs/roadmaps/multilang-migration.md`、`docs/architecture/l2-shell.md` |
| [engineering-debug-mode.md](engineering-debug-mode.md) | 进行中(P1 缺口待闭环;P1-C 已闭环) | 3.5 工程调试模式：标记文件门禁、授权/隐私/硬件输入监测与 Prompt 旁路治理 | `docs/architecture/l3-prompt-architecture.md`、`docs/configuration/overview.md` |
| [agent-os-3x-closure.md](agent-os-3x-closure.md) | 进行中(Slice A–E 已完成并合入 main;P2 收敛与 TS protocol mirror 待启动) | 3.x 生产闭环 + TS 重写门:P0 契约冻结/会话身份/durable store/恢复，P1 运维闭环，P2 治理收敛——**会话域 P0 条目的施工权威** | `docs/roadmaps/l2-multifrontend-session-layer.md`、`docs/roadmaps/production-closure-roadmap.md`、`docs/architecture/l3-memory.md` |
| [l2-agent-handoff.md](l2-agent-handoff.md) | 操作手册(随 main 演进) | L2 能力地图、TS 重写标准(§2 铁律/镜像同步/验收清单)、已知坑与运行环境——l2-multifrontend 路线图的配套操作性手册 | `docs/roadmaps/l2-multifrontend-session-layer.md`、`docs/architecture/l2-shell-engine.md`、`systems/typescript-shell-engine/README.md` |
| [l1-l2-docking.md](l1-l2-docking.md) | 进行中(D0–D2 已合入 main，默认仍 Python；G1–G6 割接阶梯待启动) | L1↔L2 线缆对接:TS-L2 × Rust-L1 协议 v1 直连;`PRAXIS_RUST_HOST` opt-in、双 host e2e、三向量互验与帧上限契约 | `docs/roadmaps/l2-ts-rewrite-mapping.md`、`docs/roadmaps/frontend-kernel-roadmap.md`、`docs/design/rust-first-kernel-rewrite.md`、`docs/roadmaps/kernel-boundary-audit.md` |
| [l2-ts-rewrite-mapping.md](l2-ts-rewrite-mapping.md) | 进行中(main 现状基线 + TS 逐模块对齐映射) | L2 TS 重写映射清单:Python3 L2 逐模块 ↔ `systems/typescript-shell-engine/`（含 bridge.py 不存在于 main 的校正与协议 v1 客户端方向） | `docs/roadmaps/frontend-kernel-roadmap.md`、`docs/roadmaps/l2-multifrontend-session-layer.md`、`docs/roadmaps/l1-l2-docking.md` |

## 设计 / 施工计划索引

路线图只登记方向与阶段;施工计划保留在 `docs/design/`,在此登记以便追溯现实进度,避免路线图与现实漂移。
已归档计划（`construction: closed`）移入 `docs/design/archive/`,经 `docs/design/POINTERS.json` 机器索引追溯,不再在此列出。

| 计划 | 状态 | 内容 |
|---|---|---|
| [kernel-rewrite-readiness-package.md](../design/kernel-rewrite-readiness-package.md) | 进行中(G4/G5 完成,G0–G3/G6 未关) | Rust 下沉前置包:边界冻结、契约、性能、外围、工具链与回退门 |
| [rust-first-kernel-rewrite.md](../design/rust-first-kernel-rewrite.md) | 进行中(R0–R2 候选切片持续累积,G6 前置) | Rust-first 独立内核重写门槛设计:R0 语义地图→R1 substrate→R2 固定总量证据→R4/R5 独立入口与 clean cutover,不读取 Python 用户数据、不做兼容替换 |

## 管理规则

- **新增路线图**:文档放入 `docs/roadmaps/` 并带英文题头 DSL（`fonds: ROADMAP`、
  `pointer: ROADMAP-*`、`construction: planned|in_progress|closed`,同 DESIGN 门禁校验）,
  在上表登记一行(状态/内容/关联),再同步 `docs/architecture/README.md` 层列表(若为子系统级变更)。
- **状态流转**:`construction` 按 规划(planned) → 进行中(in_progress) → 已闭环(closed) 迁移。
  闭环后把文档（题头 `construction: closed`）移入 `docs/design/_outgoing/` 预存区,
  提交时 doc gate 自动归档到 `docs/design/archive/003-roadmap/2026/长期/`(无缝管线,见
  `docs/design/archive-spec.md` §4),并从本表移除;归档条目经 `POINTERS.json` 索引追溯。
- **实施文档**:阶段施工计划(`*plan*.md` / `*design*.md`)保留在 `docs/design/`,
  不在本目录——路线图只登记方向与阶段,不承载施工细节。
