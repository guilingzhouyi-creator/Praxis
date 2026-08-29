---
pointer: ROADMAP-2026-08-18-007
archive_number: ROADMAP-2026-长期-007
fonds: ROADMAP
year: 2026
retention: 长期
title: "Praxis 路线图盲区补全 — 生产闭环、安全与可运维性"
author: L3
formation_date: 2026-08-18
carrier: md
classification: 内部
pages: 157
archivist: L3
reviewer: L3
archive_date: 2026-08-29
source: roadmap
keywords: []
abstract: "现有五份路线图覆盖了前端形态收敛、L1 Rust 下沉、L2 协议 v1 与 TS 重写、run_code 多语言后端、科研泛化，但存在三类盲区："
series: active
date: 2026-08-18
status: active
construction: planned
---

# Praxis 路线图盲区补全 — 生产闭环、安全与可运维性

> 状态：规划（盲区补全，未实施）
> 审计基础：主树 `main`（HEAD `33fa8c8`）的 `docs/roadmaps/` 五份路线图 + `docs/architecture/` + `systems/python-reference-runtime/` 实码比对
> 定位：**增量补全**，不替代现有路线图。它回答一个现有路线图没有正面回答的问题——"前端矩阵、Rust 下沉、TS 重写之外，Praxis 距离可生产运行还差哪些地基？"

---

## 0. 为什么需要这份补全

现有五份路线图覆盖了**前端形态收敛、L1 Rust 下沉、L2 协议 v1 与 TS 重写、run_code 多语言后端、科研泛化**，但存在三类盲区：

1. **路线图与现实漂移**：部分路线图把"已实现"写成"未动工"，或把"未实施"写成"已实施"（见 §1）。
2. **生产闭环地基缺失**：会话身份/恢复、持久化事务、备份恢复、升级回滚、可观测性、发布运维没有一条路线图正面负责。
3. **安全边界只审到执行门，未审到副作用面**：`invoke_capability` 封住了工具执行主门，但 `$` 进程执行、VFS 未挂载路径、系统变更端点、presentation 同步失败等旁路仍以约定维持。

本文件把这些盲区收敛成 **P0（生产阻断）/ P1（可靠性）/ P2（治理收敛）** 三条轨道，并给出与现有路线图的接缝。

---

## 1. 路线图与现实漂移（先修正，再规划）

| # | 漂移 | 证据 | 修正 |
|---|---|---|---|
| D1 | `frontend-kernel-roadmap.md` §3 仍称三个 shell 端点（dispatch/autocomplete/commands）为 stub | 主树 `systems/python-reference-runtime/l4/api_handlers/api_handlers_agent.py:71-130` 已接通 `l2.l2_shell.dispatch` / `completer.autocomplete` / `commands.get_registry().list()` | M1 Phase 1–3 标记为**已完成**，M1 剩余 Phase 4–6 |
| D2 | `docs/architecture/l2-shell.md` 仍写"工具执行走 `execute_tool_spec`" | 全库 grep 无 `execute_tool_spec` 生产引用；L2 工具行已走 `l1.kernel.capability.invoke_capability`（`terminal.py:244-250`） | 同步文档；Phase 5/6 显式纳入验收 |
| D3 | `kernel-boundary-audit.md` §11.2 把 Phase 0/1 整体标为 ✅，但 B4/B6/B8/B9 仍未封口 | B4 `terminal.py:200-205` 仍 `get_process_port().run(cmd)` 直跑；B6 长生命周期 Popen 未移交；B9 死 `syscall` 仍在 `__init__.py` | Phase 0 改为**部分完成**，剩余 B4/B6/B8/B9 单列 |
| D4 | `docs/design/test-runner-slicing-plan.md` 仍标"待批准" | `tests/runner.py` 已实现 `--slice/--parallel/--list-slices` 与全量 SLICES | 该设计标记为**已落地**，剩余 `tests/l4/llm` 失败项与切片 CI 收口为 P1 |
| D5 | `docs/roadmaps/README.md` 未登记已落地的 `foundation-gaps-plan.md` 与 `test-runner-slicing-plan.md` | 两文件均存在且多数阶段已合入 | README 增"设计/施工计划"索引段，避免规划再次漂移 |

> **修正进度（2026-08-22 复核；2026-08-25 更新）**：D1/D4/D5 已落地（frontend-kernel §3 已改写、README 设计索引段已建立）；
> D2 视为已清——`docs/architecture/l2-shell.md` 契约面已写 `invoke_capability` 与 51 命令；
> `l2-shell-engine.md`、`l3-tools.md` 残留的 `_execute_tool_spec` 为私有名正确引用，非过期表述；
> D3 属 L1 内核审计范围，随该路线图处置。

---

## 2. 盲区全景（现有覆盖 vs 缺口）

| 域 | 现有路线图覆盖 | 盲区 |
|---|---|---|
| L1 执行权威 | capability 单门（B1/B2/B3/B5 已封） | B4 `$` 直跑、B6 进程句柄、B8 L3A handler 捷径、B9 死 syscall |
| L1 安全不变量 | fail-closed 鉴权、posture matrix | presentation 同步失败仍 debug 吞掉；VFS 未挂载路径直接 OS；系统变更端点未逐项审计 |
| 身份 | G2 校验位、identity_uid 发行 | 无 keypair 生成/持久/轮换，`identity_verified` 无生产真值 |
| 持久化 | R1–R4 环形、persist journal、session JSON | 无 durable JSON store（原子替换/journal/checksum）；无跨子系统事务；无 backup/restore/factory-reset 路线 |
| 恢复/升级 | session loader、migration.py | session/cache/R5 schema 版本缺失；升级回滚与恢复等价性无验收 |
| 可观测性 | trace_id、error bus、StatsCenter、MonitorBus | 事件/metrics 多头未收敛；全局事件顺序未定义；审计只保证 capability 门落盘 |
| LLM/成本 | provider 注册、retry/failover | 成本/配额/流式/降级指标、provider start 失败回滚、prompt 生产遥测缺失 |
| L2/前端 | 协议 v1 纯参考、dispatch 契约钉、前端矩阵 | event projection/multiplexing/SSE/web 迁移未做；TS mirror 未建；UX/可访问性/i18n 无验收 |
| L3 会话 | L3A session 骨架、session persist/loader | 身份碰撞、reload 不可达、`input_seq` 无权威、恢复非幂等、活动会话仅内存 |
| L3 调度/工作流 | CentralScheduler、CronScheduler、ExecutionPlan | 超时/抢占不终止运行中任务；cron 重启可重复派发；ExecutionEngine 死代码 |
| L3 记忆/技能 | R5 图、R4Agent、lean traces | 技能演化无事务；canary 回滚仅降级；cache 不跨重启；CoT 隐私边界未定义 |
| 测试/CI/发布 | runner 切片、11 维 judge、CI workflows | runner 覆盖/失败项收口、fuzz/property/adversarial 测试、release 冒烟与回滚演练缺路线 |

---

## 3. 盲区清单与优先级

### P0 — 生产阻断（会话真值、恢复、持久化、剩余执行旁路）

> **条目仲裁（2026-08-22）**：本节 P0.1–P0.4 与 `agent-os-3x-closure.md` 的 P0.1–P0.6 为同一工作面
> （会话身份 / durable store / input_seq / 恢复闭环）。**施工权威归 `agent-os-3x-closure.md`**
> （Slice A–F 切片制 + 依赖序），本表保留生产盲区全景视角，条目级进度以彼处为准、验收互查 exit criteria。
> **进度（2026-08-25 复核）**：P0.1–P0.4 已随彼处 Slice A–E 完成并合入 main。
> P0.5–P0.8（剩余旁路 / 调度强制 / 执行引擎）为本表独有，不重复立项，均未实施。

| ID | 盲区 | 证据 | 验收标准 |
|---|---|---|---|
| P0.1 | 会话身份与生命周期 | 两个会话可覆写同一 terminal 的 `session_id`；`auto_reload()` 可返回 `IDLE` 却无 worker | 显式区分 `terminal_id/session_id/process_id`；create/attach/detach/close 模型化；reload 恢复可触达 RUNNING/IDLE 且失败即大声报错 |
| P0.2 | 输入序列权威 | `input_seq` 与临时 `sent_seqs` 并存；`session_json.py:32-33,79-84` 计数器仅模块级 dict，重启归零 | L3A 入口只分配一次 `input_seq`，贯穿 conversation/thought/tool/evidence；计数器持久化；重放幂等 |
| P0.3 | Durable JSON Store | 无 atomic replace/journal/checksum 抽象 | schema 版本 + 原子替换 + journal/checksum + 文件锁 + 幂等写 + 损坏 fail-closed + 明确恢复语义 |
| P0.4 | 会话恢复闭环 | loader 只重建部分图；~~`session_persist.py:301` 用单一 `AGENT_ID` 键，多会话互踩~~（已被 Slice C 的 per-session snapshot store 取代，见 `session_persist.py` `_snapshot_store`） | 从 store 重建完整会话图，保留 identity/scope；重启恢复全部活动会话；重放/恢复幂等——**✅ 随 agent-os-3x-closure Slice C 落地** |
| P0.5 | B4 `$` 旁路 | `terminal.py:200-205` 直接 `ProcessPort.run`，无 ring/gatechain/constitution | `$` 与工具执行同走 capability 门；shell 命令按 ring 门禁并审计 |
| P0.6 | B6/B8/B9 收口 | 长生命周期 Popen 游离；L3A session_loop 直调 handler；死 `syscall` 仍在 | ProcessPort 拥有全部句柄；handler 捷径仅系统内部且 agent 不可达；死 syscall 删除或重建为唯一 capability 门 |
| P0.7 | 调度强制执行 | `CentralScheduler.execute` 同步执行，`preempt/timeout` 只记日志不终止运行中 AgentLoop（`scheduler.py:108-148,205-215`） | 超时/取消真实终止执行线程且状态一致；统一执行权威收敛到 ExecutionEngine 或 pipeline |
| P0.8 | 工作流执行引擎 | `execution_engine.py:183` retry/rollback/依赖引擎生产零调用；`execution_run.py` 无重试、parallel_all 超时后不终止 | 统一执行引擎落地；超时取消真实生效；重试/回滚有幂等语义 |

### P1 — 可靠性与安全深化

| ID | 盲区 | 证据 | 验收标准 |
|---|---|---|---|
| P1.1 | 审计强制且持久 | 内核审计为内存 deque；RC 异步 best-effort；非 capability 拒绝路径不保证落盘 | 每次 capability 调用（含拒绝）同步 append；kill -9 零丢失；gate/wiring 失败即 BLOCK |
| P1.2 | presentation/harness 联动 | `harness.py` presentation 同步失败仅 `logger.debug` | 同步失败拒绝切换；code/minimal 呈现与 harness 状态一致 |
| P1.3 | VFS 唯一通路 | `fs_adapter._vfs_route` 未挂载路径保留直接 OS | 未挂载写默认拒绝（fail-closed）；symlink/`..` 逃逸测试覆盖 |
| P1.4 | 系统变更端点 | reset/reload/harness 切换默认开放下可清空系统状态 | 全部走 capability + 审计 + 显式风险确认；新增端点默认关闭 |
| P1.5 | 身份 keypair | G2 靠注入 identity，无 keypair | boot 持久化 keypair；RING≥2 未验证端到端 BLOCK |
| P1.6 | backup/restore/factory-reset | 五份 roadmap 零命中；restore 无 dry-run/校验/审计 | backup 一致性快照 + restore 前校验 + dry-run + 审计；factory-reset 幂等 |
| P1.7 | 可观测性收敛 | 事件/metrics 多头；全局事件顺序未定义 | 单一事件通道 + 单一 metrics sink；协议 v1 `seq` 与内核事件顺序一致 |
| P1.8 | LLM/provider 生命周期 | provider `start()` 失败可留状态漂移；成本/配额/降级无遥测 | start 失败回滚并留痕；成本/配额/重试/降级进入统一 metrics |
| P1.9 | 技能演化事务 + canary | candidate 与 SkillManager 写无单事务；`r4_skill_lifecycle.py:188-217` 回滚仅归档/标 deprecated，不恢复旧 active | 提交/补偿语义；canary 自动回滚/隔离/留证，回滚恢复上一 active 版本 |
| P1.10 | CronScheduler 生命周期 | 位于 L4；`_last_checked` 仅内存，重启可同分钟重复派发；队列满 `reg.submit` 返回 `""` 被静默丢弃（`cron_scheduler.py:92,207-233`） | 重启幂等；满队列告警；防重叠执行；生命周期归入统一调度权威 |
| P1.11 | 存储 schema 迁移 | FTS5 `CREATE TABLE IF NOT EXISTS` 无版本（`memory_persist.py:71`）；仅候选台账有 schema_version | 记忆/会话/缓存/R5 边均有 schema 版本 + 升级脚本 + 旧库兼容测试 |
| P1.12 | 并发与恢复测试 | 同会话 `prompt()` 无会话锁（`session_prompt.py:261`）；SQLite journal 在 xdist 下暴露锁竞争 | 并发 send 串行化；SQLite retry/locking + 重启/reload 循环测试入基线 |

### P2 — 治理与长期演进

| ID | 盲区 | 验收标准 |
|---|---|---|
| P2.1 | 配置中心收敛 | 模块级字典与 3.x 开关进入 `SettingsCenter`，默认值/校验/重启语义唯一 |
| P2.2 | 升级回滚 | 数据迁移可重放；升级有回滚路径；恢复与 replay 状态等价 |
| P2.3 | CoT/reasoning 隐私 | 推理文本不入 R4/RC/协议 result；只暴露 DecisionSummary/EvidenceRef；分级披露 |
| P2.4 | 测试与发布韧性 | runner 覆盖 100% 且 `tests/l4/llm` 修复；hypothesis property 测试 + fuzz/adversarial 测试入闸；release 冒烟 + 回滚演练 |
| P2.5 | 前端可访问性/UX/i18n | 前端矩阵验收含键盘/读屏/主题/i18n/命令可见性；ChatBox 与 IDE 面板有可测验收面 |
| P2.6 | 多租户/配额隔离 | 身份→资源→审计→数据四维隔离；租户级配额与跨租户越权测试 |
| P2.7 | 存储保留与公平性 | R4/JSONL/快照/台账有 GC 与保留策略；TimeScheduler 公平轮转接入执行路径并有集成测试 |
| P2.8 | 性能基线补全 | scheduler/cron/load-adaptive 进入 `perf-baseline.md` 与 90% 漂移门 |

---

## 4. 与现有路线图的接缝

```text
P0（会话/持久化/恢复 + B4/B6/B8/B9 + 调度/执行引擎）
   │  依赖 frontend-kernel-roadmap M1 已接通的 /api/v2/shell
   │  依赖 kernel-boundary-audit 已封的 capability 单门
   ▼
P0 完成 ──► L2 protocol v1 从"纯参考"升级为"可恢复会话层"（l2-multifrontend P2）
   │
P1（审计/VFS/身份/备份/可观测性/LLM/provider/cron/schema）
   │  依赖 P0 的 durable store 与 schema 版本
   ▼
P1 完成 ──► kernel-boundary-audit Phase 2 可据真实固定总量 Amdahl 证据选 Rust 热路径
            frontend-kernel-roadmap M3 才不是"未封口的边界上迁移"
P2（配置/schema/CoT/测试/UX/多租户/保留/性能）
   │  依赖 P0/P1 的 store、metrics、身份
   ▼
P2 完成 ──► TS L2 默认运行时（l2-multifrontend P3）与科研泛化（research-generalization）才有可信地基
```

**关键顺序判断**：Rust 下沉与 TS 重写都**不应**在 P0 完成前成为默认路径。P0 补齐的是"会话真值、恢复语义、剩余旁路、执行取消"；否则 TS/Rust 只是把不完整的运行态复制进新语言。

---

## 5. 不做什么（Non-goals）

- 不重复 `foundation-gaps-plan.md` 已闭环的端口地基（WebSocket/AuthPort/RPC/FilesystemPort/Hook）。
- 不重复 `kernel-boundary-audit.md` 的边界判定与最小内核清单。
- 不重复 `l2-multifrontend-session-layer.md` 的协议 v1 数据结构设计。
- 不提前实施科研泛化；P2.6 只做隔离与配额预留。
- 不在本文件写 Rust/TS 代码；施工计划按 README 规则放 `docs/design/`。

---

## 6. 验证与完成定义

每个 P0/P1 切片合入前必须：

1. 域内测试 + 相关基线：`python -m pytest tests/l3 tests/infra tests/l2 tests/l4 -x -q`，再跑全量。
2. 门禁：`make lint`、层导入、params 合规、`bash scripts/sh/gate-merge.sh completion`（COMPLETE）。
3. 证据保存：会话恢复、审计落盘、备份恢复、canary 回滚的 JSON/日志证据入档。
4. 文档同步：相关 `docs/architecture/*.md` 与本文状态同 commit 更新。
5. 双绿 + 双远端：分支与 main 双绿；`push-both.sh main` 推送双远端。

---

**规划结束。** 下一步：先修正 §1 的 D1–D5 漂移，再以 P0.1–P0.4 作为第一批施工切片（会话真值 + durable store + 恢复闭环），随后封 P0.5/P0.6 剩余旁路，并同步落地 P0.7/P0.8 的调度与执行引擎收敛。

