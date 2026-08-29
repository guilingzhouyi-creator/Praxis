# 员工手册库 — Workflow Library (docs/workflow/)

> 操作规范库（Employee Handbook）：Praxis 协作与构建的操作性规范总集。
> 与 归档库（`docs/design/`）、路线图库（`docs/roadmaps/`）共同构成三大自建
> 文档库；`AGENTS.md` 载命令式铁律，本库载具体操作规范——**遇到不明确的规范
> 问题，先查本库**。

## 手册索引

| 手册 | 内容 | 何时查阅 |
|---|---|---|
| `commits.md` | 提交契约 + 主链门禁：commit-msg 规则、attribution 验证、CompletionJudge、net-delta 三锁、双远端推送 | 每次提交/推送前 |
| `branching.md` | 分支策略：feature 分支、双绿合并、local-merge gate、积累质量门禁、敏感路径审查 | 建分支/合并前 |
| `collaboration.md` | 并行协作：域划分、共享文件注册、worktree 纪律、钩子矩阵 | 多 agent 并行开工前 |
| `code-of-conduct.md` | 构建环境守则：worktree gate、两个豁免、venv、文档同步、DoD | 任何代码改动前 |

## 查询规则

1. 规范问题先查本库对应手册（提交 → `commits.md`；分支 → `branching.md`；
   并行 → `collaboration.md`；构建纪律 → `code-of-conduct.md`）；
2. 查不到再查 归档库（`docs/design/POINTERS.json`，设计/评审最终真相源）与
   路线图库（`docs/roadmaps/README.md`，方向与阶段）；
3. 仍不明 → 问用户。禁止凭记忆"修正"规范。

## 门禁命令速查

| 门禁 | 命令 | 何时 |
|---|---|---|
| 完成判定（done） | `bash scripts/sh/gate-merge.sh completion` | 声明完成前 |
| 本地合并门禁 | `bash scripts/sh/gate-merge.sh local` | 合入本地 main 前 |
| 主链净增量 | `bash scripts/sh/gate-merge.sh mainline main` | 推送/合并审查 |
| 分支切换守卫 | `bash scripts/sh/check-worktree.sh` | 任何 checkout/switch 前 |
| 双远端推送 | `bash scripts/sh/push-both.sh main` | 推送 main 时（origin 先） |

## 与文档库架构联动

- 施工计划（`*plan*.md` / `*design*.md`）在 归档库（`docs/design/`）；路线图
  只登记方向与阶段，不承载施工细节。
- 文档完成（`construction: closed`）→ 移入 `docs/design/_outgoing/` → 提交时
  自动归档（`scripts/py/doc_archive.py`，见 `docs/design/archive-spec.md` §4）。
- 本库与 `AGENTS.md` 同步维护：`AGENTS.md` 只留命令式铁律与文档库导航，细则
  在本库按需查询——新增/修改规范时两处同步。
