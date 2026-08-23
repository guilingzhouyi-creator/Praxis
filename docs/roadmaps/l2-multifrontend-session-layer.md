# Praxis L2 Shell Engine 边界审计与多前端会话层路线图

> 状态：进行中（P0–P3 已完成并合入 main，逐项验收见 §6；P4 重型/移动未启动）
> 关联：`docs/roadmaps/kernel-boundary-audit.md`（L1 审计基线，Rust 前置）、`docs/roadmaps/frontend-kernel-roadmap.md`（前端矩阵 + Rust 下沉内核）、`docs/roadmaps/multilang-migration.md`（TS 槽位）、`docs/architecture/l2-shell-engine.md`（目标架构）、`docs/architecture/l2-shell.md`（现行实现描述）
> 目的：在 Web / TUI / 轻量桌面（ChatBox 类）/ VSCode 级人机共生开发平台 / 移动端 SSH 多前端落地之前，先固定 L2 的 Shell Engine 边界与**统一会话数据层协议 v1**，避免把当前"CLI command collection + 直连 L3 控制面"的现状原样复制进 TS 重写。

---

## 0. 审计基线（2026-08-16，HEAD 3d29f5e + 未提交工作树）

> ⚠️ **历史基线**：本节为 8-16 审计快照；截至 2026-08-21，P0-P3 已全部完成并合入 main（工具单门、边界迁移、协议 v1、TS 引擎四 transport + WS 对接），进展见 §6。基线结论（36/100、三项裁决、两条 CRITICAL 旁路）均已由 P0/P1 处置。

- **Shell Boundary Integrity Score：36 / 100**。分维度：Execution boundary 6/15、State ownership 5/15、Dependency direction 4/20、Shell completeness 8/20、Bypass count 8/15、Abstraction purity 5/15。
- **三个审计问题的裁决**：
  1. L2 是 Shell Engine 吗？→ **否，是 CLI command collection + 半套分派器**（parser/AST、job control、pipeline、重定向、env/cwd/history 全部缺失或为桩；默认 L3A 意图路径实测断裂）。
  2. L2 拥有非 Shell 的系统 authority 吗？→ **是**：安全裁决（注入+LLM 复核）、工作流（card approve/reject）、生命周期（spawn/kill/destroy/emergency）、配置/模型/Skill/CI/身份策略写入、harness/auto-test 安全模式、内核事件发布。
  3. 存在绕过 L3/Kernel 的副作用路径吗？→ **HEAD 存在 2 条 CRITICAL 工具执行旁路**（L2 terminal + L4 MCP 直调公开 `execute_tool_spec`），**工作树已封堵**（`invoke_gated` 单门 + `gated` 标志 + 静态门测试，未提交）；仍存 63 个 slash 命令直连 L3 内部（结构性）与 `$` 无门执行（INDIRECT 但无 approval/ring/sandbox）。
- ⚠️ 审计期间工作树被并行修改（21 文件 M，含 `shells/terminal.py`、`tool_spec.py`、`tool_pipeline_steps.py`、`gatechain.py`、`invoke.py`、`boot_steps/tools.py`、`src/l4/*`）——本基线结论以"HEAD + WT 均审计"双状态记录。

## 1. 关键证据事实

| # | 事实 | 位置 |
|---|---|---|
| E1 | L2 共 36 个模块 / 4,783 行；51 条 YAML 命令 + 63 个 `_cmd_*` handler；`config/commands.yaml` 类别仅 session/system/debug/control/memory/agent/audit/ext，无 files/job/pipeline | `src/l2`、`config/commands.yaml` |
| E2 | 依赖方向系统性违规并被制度化：`test_layer_imports.py` ALLOWLIST 共 114 条，其中 **74 条来自 L2**（67→L3、7→L4）；"L2→L1 only" 名存实亡 | `tests/infra/test_layer_imports.py:17-46` |
| E3 | 默认交互路径断裂：`_l3a_intent` 中 `from .cell.peers.l3 import get_coordinator` 解析为 `l2.l2_shell.cell`，实测任意自由文本返回 `No module named 'l2.l2_shell.cell'` | `src/l2/l2_shell/__init__.py:229` |
| E4 | HEAD 公开 `execute_tool_spec`（仅 mute/校验/middleware/ResultStore/counter，无 clearance/approval/rate/constitution/gatechain/sandbox），L2 terminal 与 L4 MCP 直调 → CRITICAL BYPASS；WT 已改名 `_execute_tool_spec` 私有化并新增 `invoke_gated` 单门（`interactive=True`），`test_single_execution_gate.py` 通过 | `src/l3/tool_system/tool_spec.py:378/381`、`src/l3/tool_system/invoke.py`、`tests/infra/test_single_execution_gate.py` |
| E5 | 三张进程/终端表并存：L1 `ProcessTable`（PCB，逻辑进程权威）、L3 `_terminals`（AgentTerminal 注册表，运行态权威）、L2 `TerminalManager`（`subprocess.Popen` + SIGTERM/SIGKILL，**全库 0 调用方，死代码**；已于 2026-08-20 P0 删除） | `src/l1/kernel/process.py:184`、`src/l3/agent_terminal/__init__.py:564`、~~`src/l2/shell_session.py:73-137`~~ |
| E6 | 配置权威碎片化 ≥4 存储且 L2 均可写：L1 `kernel.settings`（/config、/departments）、L3 `SettingsCenter`（.praxis_settings.json，/settings、/model switch）、ACB slots（/settings cell|agent）、`ci.review.*`（/ci set） | `src/l1/kernel/settings.py:175`、`src/l3/config/settings_center.py:206` |
| E7 | 事件/审计多头：L1 EventBus + L3 error_bus + observability_bus + central_security.audit_log + ProcessTable.audit_log；L2 至少写 2 读 4，含 `emit_signal(EVENT_TASK_ASSIGN)`（shell 发布内核任务路由事件） | `src/l2/l2_shell/__init__.py:218-223` |
| E8 | 安全策略内嵌 Shell：`selector.py` 自带注入模式表 + `_llm_reviewer` 回调 + allow/deny 裁决；`output_guard.py` "intercept dangerous responses" | `src/l2/selector.py:188-246,368-379`、`src/l2/l2_shell/output_guard.py` |
| E9 | 工作流/生命周期权威直连：`/card approve|reject|cancel|submit` → `CardRegistry`；`/spawn /kill /destroy /emergency /agent-restart` → L3 cell/terminals | `src/l2/l2_shell/commands/memory.py:259-363` |
| E10 | `_pipeline` 是参数级假管道（上一步 `output` 塞入下一步 args），无流连接/并发/重定向；help 文案却宣称 "auto Map/Chain/Passthrough" | `src/l2/l2_shell/commands/common.py:132-155`、`src/l2/l2_shell/commands/system.py:565` |
| E11 | `_cmd_history` 是桩（返回 `[]`）；无 cd/pwd/env/export/alias 内置；无 jobs/fg/bg/suspend/resume；`resize()` 是 no-op（"PTY resize not yet implemented"） | `src/l2/l2_shell/commands/system.py:474-478`、`src/l2/shell_session.py:44-45` |
| E12 | `/model health` 摸 `engine._provider.health`（L4 LLM 引擎私有）；`/htn` 摸 `planner._methods`；`/cache` 摸 `cell.cache`——L2 直达多处私有内部 | `src/l2/l2_shell/commands/model.py:197-209`、`extra_cluster.py:44-52`、`system.py:455-460` |
| E13 | 命令注册表三写者：L1 `CommandRegistry` 单实例，L2 导入期写 63 handler、L4 API 写 user commands、YAML/配置文件写 defaults | `src/l1/kernel/commands.py:47`、`src/l4/api_handlers/api_handlers_commands.py:51,94` |
| E14 | L2 自身无直接文件写 / 网络 / DB 副作用（grep 0 命中）——旁路全部是委托式 | 全量 grep |
| E15 | `l2-shell.md` 现行文档已过时：声称 49 命令（实际 51）、工具执行走 `execute_tool_spec`（WT 已改 `invoke_gated`） | `docs/architecture/l2-shell.md:4,91` |

## 2. 边界判定（审计 §Correctly Owned / Incorrectly Included / Excluded 摘要）

**正确属于 L2**：`dispatch` 分派循环与 alias 反查、TerminalShell 方言（/ $ ! tool help/status/history）、ShellFamily + ShellSession 路由态、补全与 i18n、命令元数据声明、`$` 经 `ProcessPort` 的转发形态、WT 工具行经 `invoke_gated` 的桥形态。

**应迁出 L2（→ L3/L4 管理面）**：注入安全裁决与 LLM 复核（selector）、agent 路由策略（selector→L3 scheduler）、card approve/reject（→L3 workflow）、spawn/kill/destroy/emergency（→L3 lifecycle）、settings/model/skill/CI/身份策略写入、harness/auto-test/MCP 安全模式、`emit_signal`、L3A 守护启动与会话生命周期控制、output_guard 策略部分、`shell_session.py`（删除）。

**应进入 L2 但目前缺失**：parser/AST/语法错误恢复、cd/pwd/env/export/alias 内置、真实 history、job control（jobs/fg/bg/wait/cancel/suspend/resume）、真实 pipeline 语义 + IO 重定向、外部命令集成、会话恢复（中断/孤儿/重启）、统一执行请求桥（slash 侧）、修复 `_l3a_intent`。

## 3. 统一会话数据层协议 v1（核心交付）

目标：**把任意前端的任意输入转换/统一为一个数据流**，同时把向内核的操作收敛为同一桥。协议为语言无关 JSON Lines（TS 重写与 Python3 L3 可互操作）。

```json
{"v":1,"session_id":"s-…","seq":42,"ts":1723812345.678,"trace_id":"tr-…","kind":"intent","payload":{…}}
```

- `kind`：`intent`（自然语言/!方言 → L3 AgentLoop）、`command`（结构化 / 命令 → 分派表）、`event`（状态/进度/元数据）、`result`（一次性渲染就绪结果）、`stream_chunk`（增量输出）、`control`（attach/detach/resume/recovery/ack）、`ack`（消费确认，恢复游标）。
- **转换规则**：`/status` → `command`；`!scout …@cell/agent` → `intent{type:"scout"}`；`$ ls` → `command{name:"__system"}`；`a | b` → `command{name:"__pipeline", stages:[…]}`（仅语义）；web `POST /api/v2/shell` 与移动 SSH 行均为同一 envelope 的不同 transport。
- **Multiplexing**：一个 `ShellSession` 可绑 N 个前端视图，每视图持有 `ack_seq` 游标；Event Projection 将同一会话状态投影为各前端形状（web JSON / TUI 表格 / 桌面富文本 / IDE 类 LSP）。
- **Session Recovery**：`control{kind:"recovery", last_acked:N}` → L2 从有界 outbox 重放未 ack 窗口后重挂；**会话真值在 L3（SessionManager）与 L1（内核态），L2 只持路由视图 + outbox**——L2 重启绝不 fork Agent 状态。
- **向内核操作**：工具 → `invoke_gated`；`$` → `ProcessPort`；slash 控制命令 → 待建的 **L3 command bridge**（替换 63 个直连）；事件 → 仅 L1 拥有的事件走内核 API，其余走 L3 bus。

## 4. 前端矩阵与适配器

| 前端 | 形态 | 适配器要点 | 当前状态 |
|---|---|---|---|
| Web GUI | L4 API + 现有 /shell 端点 | 已有 envelope 封装；补 stream_chunk/SSE | 部分（/shell、/autocomplete、/commands 已接） |
| TUI | 终端全屏 | 复用 TerminalShell 方言；协议 v1 渲染表格/流 | contract-ready（l5-user.md），未建 |
| 轻量桌面（ChatBox 类） | 桌面聊天壳 | 只消费 result/stream_chunk + intent 输入；零 L3 知识 | 未建 |
| VSCode 级人机共生开发平台 | 编辑器内 Agent 面板 | 事件投影 + 文件 diff 流 + 多路会话 + LSP 风格协议；承载最大并发 | 未建（远期） |
| 移动端 SSH | 移动终端/SSH 通道 | transport = stdio/SSH；协议 v1 在通道内逐行编码 | 未建（远期） |

所有适配器共享同一 `Session/Interaction State/Command-Intent/Event Projection/Multiplexing/Session Recovery` 核心——这正是"L2 需要承载的"统一会话数据层。

## 5. TS 重写路径

| 现 Python3 模块 | TS 模块（已落地） | 说明 |
|---|---|---|
| `dispatch` + `shlex` | `engine/parser.ts` + `engine/dispatcher.ts` ✅ | 纯函数，无副作用 |
| `ShellSession` / `ShellFamily` | `engine/session.ts`（SessionView + 三形状投影）✅ | JSON 可序列化 |
| `shells/*` | `engine/transports/*`（stdio/http/ws/ssh）+ `session.ts` 投影形状 ✅ | 每前端一个适配器 |
| 内置命令 | `engine/builtins.ts`（lang/help/clear）✅ | 本地纯展示，其余回退桥 |
| 执行调用 | `engine/bridge.ts`（单一客户端）+ `line-transport.ts` ✅ | 向 Python3 L3 宿主说协议 v1（stdio/WS/HTTP/SSH）；**L3 Agent 逻辑保持 Python3 不动** |
| `i18n.py` | locale 数据 + `lang` builtin ✅ | 同 locale 数据（locales/*.yaml） |

硬约束：TS L2 是 L3 的**纯投影器 + 分派器 + 桥客户端**，绝不重实现 AgentLoop/Tool Pipeline/Workflow/Scheduler/Memory/Planning。

构建外围边界：`scripts/py/praxis_automation.py` 及其 manifest/性能 runner 不属于
L2 协议和 TS 引擎迁移面。P3 只迁移 `parser/dispatcher/session/builtins/bridge.ts`；
自动化脚手架继续在宿主构建环境运行，并通过 `ProcessPort` 调用基准/质量命令。
TS L2 不应复制这些 Python3 CLI，也不应把性能报告当作会话协议事件；需要展示时，
只能通过协议 v1 的结果/事件投影消费版本化报告。

## 6. 阶段路线图

### 6.0 状态总览

| 阶段 | 状态 |
|---|---|
| P0 止血 | ✅ |
| P1 边界迁移 | ✅ |
| P2 协议 v1 | ✅ |
| P3 TS 引擎 | ✅ 引擎+四 transport+WS 对接（2026-08-21 合入 main；**08-22 被 edc5caa6 移除，08-23 在 feature/l2-ts-rewrite 21a118cf 恢复**） |
| P4 重型/移动 | ⏳（起点见 §6.5） |

### 6.1 P0 止血 — ✅（2026-08-20）

- 工具执行走 `l1.kernel.capability.invoke_capability`（W6.1 单门 + fail-closed + audit）；G1 fail-closed；`_execute_tool_spec` 私有化；`_l3a_intent` 修复（改走 `l3.cell.peers.l3`）；删除 `shell_session.py` 死代码。
- 验收：门禁测试绿；默认 L3A 意图路径可用；L2 无 Popen。

### 6.2 P1 边界迁移 — ✅（2026-08-20/21）

- **L3 command bridge 清零**：`src/l2/bridge.py` 为 L2→L3 唯一受控边界（92 函数 / 49 allowlist）；26 个文件 allowlist 条目清零；非桥 L2→L3 直连 44 → 0（余 8 条 L2→L4 独立边界：ci_review/mcp_bridge/api_handlers/llm/cron/i18n）。
- **selector**：dict 数据 API（`cell_ids`/`cell_liveness`/`cell_agent_reachable`/`cell_territory`，对象句柄零泄漏）；注入策略迁 L3（`l3/services/injection_guard.py`——模式表/阈值裁决/LLM reviewer 下沉）。
- **配置权威收敛**：L2 配置写面统一经桥 `settings_set` → L3 settings_center（`/config`、`/settings global`、`/ci set`、`/ci toggle`）；L1 kernel.settings 只作默认值只读面；ACB 槽位写属绑定域保留。
- **i18n 收编**：47 处 f-string error 串 → `shell.app_error.*`（31 key × 4 locale）；`test_i18n_l2_regression` 正则已补 f-string 盲区。
- 验收：业务文件零直连（仅 bridge.py 保留）；策略写操作全部经桥。

### 6.3 P2 协议 v1 — ✅（2026-08-20/21）

- **参考实现**：`src/l2/protocol/`（envelope/schema/records/host/projection）+ 契约钉；**TS parity mirror**：`packages/protocol-ts/`（共享 fixture + Vitest）。
- **接入**：web 端点双模式（`/api/v2/shell` 检测 envelope 走共享 ProtocolHost，旧 dict 兼容）；会话值层 `SessionIdentity`；多前端统一调用（`SessionCursor` 每视图游标 + 单一 ProtocolHost 入口，前端只做线格式适配）。
- **multiplexing**：Outbox 非破坏性 ack + 共享水位按落后视图（`_advance_shared_cursor`）；3 个补丁：共享水位恒 -1 修复、host stdout 捕获（防污染 JSONL）、stdio 单次校验。
- **投影与镜像**：event projection（web/TUI/desktop 三形状 + 未知回退 web）；TS 镜像同步（Outbox 非破坏性/unacked(after_seq)/SessionCursor.ack 与 Python3 逐字段对齐）；dispatch 热路径优化（`/lang` -7%、`/history` -22%）。
- 验收：多前端（五前端矩阵任一组合）同会话并发可恢复；断线重放无丢失；TS 镜像测试与 Python3 契约钉同绿；TS 仍不拥有运行时状态。

### 6.4 P3 TS 引擎 — ✅ 基本完成（2026-08-21，08-23 在分支恢复）

> ⚠️ **恢复记录（2026-08-23）**：引擎曾于 2026-08-21 合入 main，
> 但 08-22 被 `edc5caa6`（GPT-5，`refactor(l2): align language protocol
> boundary`）整体移除（仅保留 envelope/records 协议镜像），并顺带把 TS
> `Outbox.ack` 改成破坏性 shift（与 Python3 单真相源的非破坏性 ack 漂移）。
> 2026-08-23 在 `feature/l2-ts-rewrite` `21a118cf` 恢复引擎 11 文件 + 5
> 测试，并回退该 ack 漂移（`unacked(afterSeq)` 恢复、非破坏性语义还原）。
> **当前 main 上无 TS 引擎**——P4 工作以该分支为基础，合入时随分支带回。

- **已落地（2026-08-21，恢复于 feature/l2-ts-rewrite）**：
  - 引擎 6 模块：`parser.ts`（引号分词）、`dispatcher.ts`（注册表 + `listCommands` + 回退桥标记）、`bridge.ts`（**异步 Transport 契约**）、`session.ts`（`SessionView` + 三形状投影）、`builtins.ts`（lang/help/clear）、`line-transport.ts`（共享引擎：ack 边界 + 超时/上限 + 并发拒绝）。
  - 四 transport 适配器：`stdio.ts`（Node readline）/ `http.ts`（fetch `/api/v2/shell`）/ `ws.ts`（原生 WebSocket）/ `ssh.ts`（ssh2 channel）——五前端矩阵适配器全部就位。
  - 真实端到端：`tests/e2e.stdio.test.ts`（spawn Python3 host：command 往返 + attach/replay）+ `tests/transports.test.ts` 6 例（Vitest 29 passed，tsc 干净）。
  - WS 端点对接：`l4/ws/ws_bridge.py` 协议 v1 envelope 分支（与 RPC 双模式共存，`ws://host:8081`；`tests/l4/test_ws_bridge.py` 往返测试 2 例）。
- **剩余**：真实 SSH 端点（远端 stdio host 已通——按需接入）+ 五前端矩阵真实接入。
- **重写标准**：见 [l2-agent-handoff.md](l2-agent-handoff.md) §2（跨语言契约 / 桥 API 对应 / 铁律 / 镜像同步 / 验收清单）。
- 验收：TS 引擎跑通 web/TUI/轻量桌面；L3 零改动；协议 v1 作为唯一跨语言契约。

### 6.5 P4 重型/移动 — ⏳（起点：feature/l2-ts-rewrite，2026-08-23）

- **VSCode 级共生平台**（事件投影 + diff 流 + 多路会话）与**移动 SSH 适配器**。
- 起点：引擎已恢复于 `feature/l2-ts-rewrite`（§6.4 恢复记录），P4 在分支上
  推进，合入时随分支带回 main（main 当前无 TS 引擎）。
- 验收：五前端矩阵全部接入协议 v1。

> 详细文件/符号级索引、运行环境与已知坑：→ [l2-agent-handoff.md](l2-agent-handoff.md)

## 7. 落地顺序（与内核审计衔接）

1. ✅ 先合入 WT 边界硬化（工具单门）——否则一切协议/TS 工作都建立在旁路之上。（P0，已合入）
2. ✅ L3 command bridge 与 L2 边界迁移并行（P1），其完成是 TS 重写（P3）的前置。（P1/P3 已完成并合入）
3. 与 `kernel-boundary-audit.md` 的衔接点：进程/事件/配置双权威收敛由 L1 路线图负责，L2 只要求"单一桥 + 单一写面"；L1 Rust 化完成后，协议 v1 的 bridge 目标地址变为 Rust kernel 的 capability 边界，Python3/TS 两侧均无感。
4. 自动化外围只通过 `ProcessPort`、版本化报告和未来的 evidence/observability Port
   与宿主连接；不得新增 L2→L3 直连或把 runner 嵌入 TS Shell。
5. 全程保持：**L2 不拥有任何最终 authority**——安全/调度/业务/Agent/LLM/模型/工具治理逻辑一律不得塞入 Shell。

## 8. TS 重写架构预留（2026-08-21）

### 8.1 模块映射（最终版）

完整映射见 handoff §1.7（L2 全层）与 §1.9（host 职责 → TS 模块）；本节为路线图视角摘要：

| 域 | Python3 | TS（已落地/预留） |
|---|---|---|
| 协议契约 | `protocol/envelope.py`、`records.py` | `protocol-ts/src/{envelope,records}.ts` ✅ |
| 引擎 | `l2_shell` 路由语义 | `engine/{parser,dispatcher,builtins}.ts` ✅ |
| 会话 | `shells/session.py` + host 状态容器 | `engine/session.ts`（SessionView）✅ |
| 桥 | `bridge.py`（92 函数，域分组） | `engine/bridge.ts`（1:1 转发）✅ |
| 传输 | `host.run()`（stdio）+ ws 桥 | `engine/transports/*`（stdio/http/ws/ssh）✅ |

### 8.2 优化继承表

Python3 侧协议优化的 TS 对应见 handoff §1.9 表——TS 侧**天然继承全部**（无 shlex / import 语句 / JSON 往返成本），唯一需保持一致的是 outbox 窗口与配置默认值（来自 params / praxis.yaml 真相源）。

### 8.3 后续里程碑

- **P3 收尾**：真实 SSH 端点接入（适配器已按 §2.6 标准预留）+ 五前端矩阵真实接入（web / TUI / desktop / SSH / 移动）。
- **TS 重写阶段**：①协议层（envelope / records / line-transport——已落地）→ ②引擎（parser / dispatcher / session / builtins——已落地）→ ③host 对端（Python3 保持权威——TS 只作客户端）→ ④前端矩阵真实接入。
- **文档基线**：handoff §1.7 / §1.8 / §1.9 + §2 标准为重写期间唯一参考；代码内 TS 参考注释为第二层指引。
