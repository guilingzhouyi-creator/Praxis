# Praxis Roadmaps — 集中路线图索引

Praxis 的路线图文档集中于此目录统一管理。每条路线图登记其状态、阶段与
关联文档;实施文档与架构参考保留在原层目录,但在此登记索引。

| Roadmap | 状态 | 内容 | 关联 |
|---|---|---|---|
| [frontend-kernel-roadmap.md](frontend-kernel-roadmap.md) | 进行中(M1 剩余 Phase 4–5;Phase 6 文档同步已完成) | 前端矩阵(TUI/桌端/Web)+ Rust 下沉 L1 内核;M1 三端点已接通 | `docs/roadmaps/multilang-migration.md`、`docs/architecture/l5-user.md`、`docs/architecture/l2-shell.md`、`docs/roadmaps/production-closure-roadmap.md` |
| [production-closure-roadmap.md](production-closure-roadmap.md) | 规划(盲区全景;P0 会话面施工权威在 agent-os-3x-closure——其 Slice A–E 已合入 main,P0.5–P0.8 未实施) | 生产闭环、安全与可运维性:P0 会话/恢复/持久化/剩余旁路,P1 审计/VFS/身份/备份/可观测性/LLM/cron/schema,P2 治理收敛 | `docs/roadmaps/kernel-boundary-audit.md`、`docs/roadmaps/l2-multifrontend-session-layer.md`、`docs/roadmaps/frontend-kernel-roadmap.md`、`docs/architecture/security-evidence.md`、`docs/architecture/l3-memory.md` |
| [research-generalization.md](research-generalization.md) | 前瞻规划(Not Started) | 科研场景泛化:explorer 角色、假设管理、阴性知识库 | `docs/architecture/l3-memory.md`(R5 图) |
| [multilang-migration.md](multilang-migration.md) | 规划(Python3 后端已交付,TS/Rust 槽位) | run_code / Code Mode (PTC) 多语言后端转换路径 | `docs/roadmaps/frontend-kernel-roadmap.md`、`docs/architecture/l3-tool-presentation.md` |
| [kernel-boundary-audit.md](kernel-boundary-audit.md) | 进行中(G1/G2 已切片验收,M3 待闭环) | L1 Kernel 边界审查——Rust 重写前置基线(评分 42/100;绕过路径/缺失不变量/最小内核/落地顺序) | `docs/roadmaps/frontend-kernel-roadmap.md`、`docs/roadmaps/multilang-migration.md`、`docs/architecture/l1-kernel.md`、`docs/design/rust-readiness-hardening-plan.md`、`docs/design/kernel-rewrite-readiness-package.md`、`docs/design/reviews/2026-08-18-kernel-readiness-preflight.md` |
| [l2-multifrontend-session-layer.md](l2-multifrontend-session-layer.md) | 进行中(第三态:P0 单门与 P3 TS 引擎+三批/P4 扩展在 main;P1 桥/注入守卫与 P2 projection/web 接线被 edc5caa6 移除后未回补) | L2 Shell Engine 边界审计(评分 36/100)+ 多前端(Web/TUI/桌端/IDE/移动SSH)统一会话数据层协议 v1 + TS 重写路径(P0–P4) | `docs/architecture/l2-shell-engine.md`、`docs/roadmaps/kernel-boundary-audit.md`、`docs/roadmaps/frontend-kernel-roadmap.md`、`docs/roadmaps/multilang-migration.md`、`docs/architecture/l2-shell.md` |
| [engineering-debug-mode.md](engineering-debug-mode.md) | 进行中(P1 缺口待闭环;P1-C 已闭环) | 3.5 工程调试模式：标记文件门禁、授权/隐私/硬件输入监测与 Prompt 旁路治理 | `docs/design/reviews/2026-08-16-engineering-debug-review.md`、`docs/architecture/l3-prompt-architecture.md`、`docs/configuration/overview.md` |
| [agent-os-3x-closure.md](agent-os-3x-closure.md) | 进行中(Slice A–E 已完成并合入 main;P2 收敛与 TS protocol mirror 待启动) | 3.x 生产闭环 + TS 重写门:P0 契约冻结/会话身份/durable store/恢复，P1 运维闭环，P2 治理收敛——**会话域 P0 条目的施工权威** | `docs/roadmaps/l2-multifrontend-session-layer.md`、`docs/roadmaps/production-closure-roadmap.md`、`docs/architecture/l3-memory.md` |
| [l2-agent-handoff.md](l2-agent-handoff.md) | 操作手册(随 main 演进) | L2 能力地图、TS 重写标准(§2 铁律/镜像同步/验收清单)、已知坑与运行环境——l2-multifrontend 路线图的配套操作性手册 | `docs/roadmaps/l2-multifrontend-session-layer.md`、`docs/architecture/l2-shell-engine.md`、`systems/typescript-shell-engine/README.md` |
| [l1-l2-docking.md](l1-l2-docking.md) | 进行中(D0 与 D1a–D1d 已落 main;D2 首片已在 feature 分支完成，默认仍 Python) | L1↔L2 线缆对接:TS-L2 × Rust-L1 协议 v1 直连;`PRAXIS_RUST_HOST` opt-in、双 host e2e、三向量互验与帧上限契约 | `docs/roadmaps/l2-ts-rewrite-mapping.md`、`docs/roadmaps/frontend-kernel-roadmap.md`、`docs/design/rust-first-kernel-rewrite.md`、`docs/roadmaps/kernel-boundary-audit.md` |

## 设计 / 施工计划索引

路线图只登记方向与阶段;施工计划保留在 `docs/design/`,在此登记以便追溯现实进度,避免路线图与现实漂移。

| 计划 | 状态 | 内容 |
|---|---|---|
| [foundation-gaps-plan.md](../design/foundation-gaps-plan.md) | 已闭环 | L1 端口地基(WebSocket/AuthPort/RPC/FilesystemPort/Hook),6 缺口已合入 |
| [rust-readiness-hardening-plan.md](../design/rust-readiness-hardening-plan.md) | 进行中(WS1/WS2 已落地) | Python3 侧封口,先于 Rust 重写;单一执行门 + fail-closed 授权 |
| [kernel-rewrite-readiness-package.md](../design/kernel-rewrite-readiness-package.md) | 进行中(G4/G5 完成,M3/G6 阻塞) | Rust 下沉前置包:边界冻结、契约、性能、外围、工具链与回退门 | `../design/reviews/2026-08-18-kernel-readiness-preflight.md` |
| [test-runner-slicing-plan.md](../design/test-runner-slicing-plan.md) | 已落地(切片实现,剩余 `tests/l4/llm` 与 CI 收口) | `tests/runner.py` 全量 SLICES + `--slice/--parallel/--list-slices` |
| [l3a-compression-v2-migration.md](../design/l3a-compression-v2-migration.md) | 进行中(Phase 0 计划落定) | L3A 上下文压缩子系统 3.1 补充缺口绞杀者迁移:装配工厂/协议选型/配置持久化/错误风暴/RC 闭环/敏感语义/压缩比基准 | `docs/architecture/l3-memory.md`、`docs/architecture/l3a-central.md`、`docs/architecture/perf-baseline.md` |
| [l1l2-docking-execution-plan.md](../design/l1l2-docking-execution-plan.md) | 进行中(D0 与 D1 机制切片已落 main;D2 待启动) | L1↔L2 对接施工级计划:worktree 分支拓扑(D0/D1a–D1d/D2 提交序列)、统一验证门与操作员批准合入门——`l1-l2-docking.md` 的执行载体 |
| [rust-first-kernel-rewrite.md](../design/rust-first-kernel-rewrite.md) | 进行中(R0–R2 候选切片持续累积,G6 前置) | Rust-first 独立内核重写门槛设计:R0 语义地图→R1 substrate→R2 固定总量证据→R4/R5 独立入口与 clean cutover,不读取 Python 用户数据、不做兼容替换 |

## 管理规则

- **新增路线图**:文档放入 `docs/roadmaps/` 并在上表登记一行(状态/内容/关联),再同步
  `docs/architecture/README.md` 层列表(若为子系统级变更)。
- **状态流转**:`规划(未动工)` → `进行中` → `已闭环`。闭环后移入
  `docs/design/archive/` 归档(见 `foundation-gaps-plan.md` 先例),并从本表移除。
- **实施文档**:阶段施工计划(`*plan*.md` / `*design*.md`)保留在 `docs/design/`,
  不在本目录——路线图只登记方向与阶段,不承载施工细节。
