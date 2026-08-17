# Praxis Roadmaps — 集中路线图索引

Praxis 的路线图文档集中于此目录统一管理。每条路线图登记其状态、阶段与
关联文档;实施文档与架构参考保留在原层目录,但在此登记索引。

| Roadmap | 状态 | 内容 | 关联 |
|---|---|---|---|
| [frontend-kernel-roadmap.md](frontend-kernel-roadmap.md) | 规划(未动工) | 前端矩阵(TUI/桌端/Web)+ Rust 下沉 L1 内核 | `docs/roadmaps/multilang-migration.md`、`docs/architecture/l5-user.md`、`docs/architecture/l2-shell.md` |
| [research-generalization.md](research-generalization.md) | 前瞻规划(Not Started) | 科研场景泛化:explorer 角色、假设管理、阴性知识库 | `docs/architecture/l3-memory.md`(R5 图) |
| [multilang-migration.md](multilang-migration.md) | 规划(Python 后端已交付,TS/Rust 槽位) | run_code / Code Mode (PTC) 多语言后端转换路径 | `docs/roadmaps/frontend-kernel-roadmap.md`、`docs/architecture/l3-tool-presentation.md` |
| [kernel-boundary-audit.md](kernel-boundary-audit.md) | 规划(审计基线,未实施) | L1 Kernel 边界审查——Rust 重写前置基线(评分 42/100;绕过路径/缺失不变量/最小内核/落地顺序) | `docs/roadmaps/frontend-kernel-roadmap.md`、`docs/roadmaps/multilang-migration.md`、`docs/architecture/l1-kernel.md`、`docs/design/rust-readiness-hardening-plan.md` |
| [l2-multifrontend-session-layer.md](l2-multifrontend-session-layer.md) | 规划(审计基线,未实施) | L2 Shell Engine 边界审计(评分 36/100)+ 多前端(Web/TUI/桌端/IDE/移动SSH)统一会话数据层协议 v1 + TS 重写路径(P0–P4) | `docs/architecture/l2-shell-engine.md`、`docs/roadmaps/kernel-boundary-audit.md`、`docs/roadmaps/frontend-kernel-roadmap.md`、`docs/roadmaps/multilang-migration.md`、`docs/architecture/l2-shell.md` |

## 管理规则

- **新增路线图**:文档放入 `docs/roadmaps/` 并在上表登记一行(状态/内容/关联),再同步
  `docs/architecture/README.md` 层列表(若为子系统级变更)。
- **状态流转**:`规划(未动工)` → `进行中` → `已闭环`。闭环后移入
  `docs/design/archive/` 归档(见 `foundation-gaps-plan.md` 先例),并从本表移除。
- **实施文档**:阶段施工计划(`*plan*.md` / `*design*.md`)保留在 `docs/design/`,
  不在本目录——路线图只登记方向与阶段,不承载施工细节。
