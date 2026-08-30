---
pointer: ROADMAP-2026-08-15-001
archive_number: ROADMAP-2026-长期-001
fonds: ROADMAP
year: 2026
retention: 长期
title: "Praxis 前端与内核多语言路线图"
author: L3
formation_date: 2026-08-15
carrier: md
classification: 内部
pages: 1077
archivist: L3
reviewer: L3
archive_date: 2026-08-29
source: roadmap
keywords: []
abstract: "Praxis 的后续前端将覆盖四种形态：TUI、轻量化桌端 App（开箱即食的 ChatBox）、"
series: active
date: 2026-08-15
status: active
construction: in_progress
---

# Praxis 前端与内核多语言路线图

> 状态：G4 自动化外围已闭合；G5 Rust/TS 迁移脚手架已启动；Rust-first 独立内核重写仍按 R0–R5 与 M1–M4 门槛推进
> 关联决策：`docs/decisions/praxis-tech-stack-decision.md`（内核纯 Python）、`docs/decisions/praxis-mvp-decision.md`
> 关联设计：`docs/design/archive/001-design/2026/永久/DESIGN-2026-永久-022_load-adaptive-pool-design.md`、`docs/architecture/l5-user.md`、`docs/architecture/l2-shell.md`

---

## 0. 概述

Praxis 的后续前端将覆盖四种形态：**TUI**、轻量化桌端 App（开箱即食的 ChatBox）、
重量化桌端 App（VSCode 级的人机共生开发平台）、远程协作 Web 端。本路线图回答两个问题：

1. **前端多样化如何影响 L2 Shell 变体规模？** —— 结论：Shell 变体收敛到"交互范式"级（约 3 个），
   不随前端数量增长；前端差异全部落在渲染/绑定层，不触及 L2 引擎。
2. **Rust 重写底层 L1 何时做、先优化哪个热路径？** —— 结论：Rust-first 独立内核是**既定方向**；
   Amdahl 缩放曲线决定**实现顺序与时机**，不要求复制 Python 的类布局或用户数据。

---

## 1. 设计原则与约束

| 原则 / 约束 | 出处 | 含义 |
|---|---|---|
| **语言无关契约** | l5-user.md / AGENTS.md | 前端只经 `/api/v2/*` + WS/SSE 与内核通信；内核可多语言化而不重写前端 |
| **内核保持纯 Python** | tech-stack-decision ADR（早期判断） | 早期（7月，discussing 态）认为引入 Rust/C++ 不值；已被 8 月 load-adaptive 设计的 Rust 迁移路径覆盖——Rust 下沉内核是既定方向 |
| **端口抽象，鸭式类型** | cross-cutting.md | `register_port/get_port`；换语言只改适配器，不改内核调用方 |
| **契约版本化** | AGENTS.md | `/api/v2/*` 唯一契约，manifest 唯一事实源，三通道（HTTP/WS/RPC）共享 handler |
| **前端 = 纯 HTTP 客户端** | l5-user.md | TUI/desktop 无进程内 import，为将来多语言化留契约 |

---

## 2. 前端矩阵 → 范式级 Shell 变体

Praxis 的 L2 采用"方言适配器 + 共享引擎"（`docs/architecture/l2-shell.md`）：一个新前端通过
`ShellFamily.resolve(frontend)` **绑定**到一个方言，而非新增引擎逻辑。因此 **Shell 变体的数量
由"交互范式"决定，不由"产品数量"决定**。

| 前端 | 交互范式 | Shell 变体（方言） | 主入口契约 |
|---|---|---|---|
| TUI | 全屏会话 | `terminal`（现有） | `!intent` → L3A session |
| ChatBox 轻桌端 | 会话式聊天 | `chat` / `session`（新增） | `!intent` / `/api/v2/l3a/sessions*` |
| VSCode 级重桌端 | 面板驱动工作台 | `workspace`（新增） | `/command` + 结构化面板（file tree / diff / approval / plan） |
| Web 工作台 | 远程协作开发 | `workspace`（复用） | 同上 + SSE/WS 实时 |

**关键推论：**

- **ChatBox 是"前端薄、后端厚"的典型**。"开箱即食聊天，后端封装强大引擎调度与任务规划"——
  任务规划/调度在 **L3**（`CardRegistry` / L3A / scheduler），不在 L2。ChatBox 只提交自然语言意图，
  新增一个会话式方言 + 渲染器即可，**不新增任何引擎逻辑**。
- **命令可见性分化**（哪些命令对 ChatBox 暴露 vs VSCode 工作台）用 `CommandDef.category` +
  前端按 category 过滤实现，**不需要新 Shell**。
- **新增前端 = 新增一个渲染壳，复用已有契约**，不引起 Shell 变体膨胀。

---

## 3. L2 抽象完整（Phase 1–6，纯 Python，留转化接口）

现状：**语言无关契约框架已就绪，且 Phase 1–3 已接通（M1 部分完成）**。三个端点不再是 stub：

```
POST /api/v2/shell                  → _shell_dispatch    → l2.l2_shell.dispatch(text, session)
GET  /api/v2/shell/autocomplete     → _shell_autocomplete → l2.l2_shell.completer.autocomplete(line)
GET  /api/v2/shell/commands         → _shell_commands    → l1.kernel.commands.get_registry().list(category)
```

仍待完成：Phase 4（会话收尾——`systems/python-reference-runtime/l2/l2_shell/state.py` shim 仍在）与 Phase 5（底层边界文档标注转化位）。
Phase 6 已完成（2026-08-25 复核）：`l2-shell.md` 契约面已写 `invoke_capability`（boot 接线 ToolPipeline）
与 51 YAML 命令，不再有 `execute_tool_spec` 过期表述。

| Phase | 动作 | 落点 |
|---|---|---|
| **1. 接通命令执行** | `_shell_dispatch` stub → `l2.l2_shell.dispatch(text, session)` | `systems/python-reference-runtime/l4/api_handlers/api_handlers_agent.py` |
| **2. 接通补全** | `_shell_autocomplete` stub → `l2.l2_shell.completer.autocomplete()` | 同上 |
| **3. 接通命令列表** | `_shell_commands` stub → `l1.kernel.commands.get_registry().list()` | 同上 |
| **4. 会话收尾** | `ShellSession` 全接管，移除 `state.py` deprecated shim | `systems/python-reference-runtime/l2/l2_shell/state.py` |
| **5. 底层边界留位** | 确认 process/fs/terminal 走 `ProcessPort`/`FilesystemPort`/`WorkerPort` + L4 通道；仅文档标注转化位 | `l2-shell.md` "Bottom-layer boundary" 表格（fs/worker 已接 port，`ProcessPort` 为 Rust 下沉候选） |
| **6. 文档同步** | 更新 `docs/architecture/l2-shell.md` 契约面 | l2-shell.md — ✅ 完成（契约面已写 `invoke_capability`，2026-08-25 复核） |

> 接通 stub 是纯 Python 改动，完全符合现有架构；前端矩阵也强化了接通 `/api/v2/shell`
> 语言无关端点的价值——前端越多，语言无关契约的价值越大。

---

## 4. Rust 重写底层 L1 的既定路线

> **边界审计基线**：`docs/roadmaps/kernel-boundary-audit.md` 已对当前 L1 完成系统内核边界审查
> （评分 42/100）。Rust 下沉前必须先收敛执行权威（唯一 invoke-capability 门）、修复 B1/B2/B3
> 绕过路径与 fail-open 鉴权，避免把错误边界复制进 `l1_kernel_rs`——审计 §5/§10/§11 为前置封口清单。

### 4.1 演进脉络（早期判断 → 既定方向）

早期 ADR `docs/decisions/praxis-tech-stack-decision.md`（2026-07-21，`status: discussing`）
曾判断"当前不值得引入 Rust"——瓶颈是 LLM API（500ms–5s），非计算路径（微秒级）。**但该判断
已被后续设计演进覆盖**：`docs/design/archive/001-design/2026/永久/DESIGN-2026-永久-022_load-adaptive-pool-design.md`（2026-08）已为
Rust 重写铺路。当前 preflight 分支仍用 Python 作为语义参考，但未来 Rust 内核是独立新构建，
可重新选择常量、状态布局、调度和协议版本。因此 **Rust 重写底层 L1 是路线图的既定方向**，
不是被排除的选项。具体边界见 `docs/design/rust-first-kernel-rewrite.md`。

### 4.2 优先级门槛（缩放曲线决定"先优化哪个"，而非"是否做"）

`cross-cutting.md` 明确：**Amdahl 缩放曲线**（`bench_scale.py --agents 1,2,4,8`）是
"Rust 内核迁移优先级"的主要证据：

- 串行占比 P 高 ⇒ 优先移植/优化调度器与共享锁；
- P 低 ⇒ 瓶颈在 LLM 调用延迟，Rust 收益有限，推迟到需要时再做。

判定的是**迁移顺序与时机**，不改变"Rust 下沉内核"这一方向。

证据必须来自已完成的真实 L1 基准：`bench_scale.py --mode amdahl --agents 1,2,4,8 --json <result>`
在目标平台上完整执行。该工作负载固定总 work items，并实际穿过 `ThreadPoolWorker`、`Mutex` 与
`RingChannel`；报告必须显示每档完成数等于固定总量，同时保留吞吐、操作延迟、调度排队等待和锁等待。
**只有这样的已完成 JSON 结果才能作为 Rust 优先级证据。** 合成 `sleep`/hash、每个 worker 重复整套工作，
或未实际运行的示例数字都不能用于决定迁移顺序。

### 4.3 独立构建路径

1. 先建立 R0 语义地图：区分必须保留的不变量、可重设计的 Python 行为和明确移除的副作用。
2. Rust 侧建立独立的 typed hot path；Python 参数和 `praxis.yaml` 只提供初始语义输入，
   不成为 Rust 内部布局或性能策略的唯一真源。
3. 用固定总量基准比较 Rust-native 数据结构、队列、锁和批处理策略；以 p95/p99、CPU、内存、
   queue/lock wait 和 drop rate 选择方案，而不是按 Python 类逐个翻译。
4. 仅对仍保留的 TS/L2/诊断边界定义版本化 wire contract；不为不存在的用户数据迁移保留兼容层。
5. 新内核以独立入口和新状态目录启动；Python、DVG、R5/Mer、AgentLoop 的策略/执行和提示词
   不进入 Rust kernel。仅允许经过向量与并发验证的 AgentLoop 逻辑路由/身份状态候选作为
   session/terminal 边界，前端通过明确版本的协议桥接。

### 4.4 演进模型澄清（语义基线 vs 独立实现）

**目标不是 Python 兼容替换，而是以 Python 为语义参考的独立 Rust 构建：**

```
R0 语义地图（Python 参考 + 安全/控制不变量）
   │
   ▼
R1 Rust-native substrate（typed state + bounded queues + metrics）
   │
   ▼
R2/R3 fixed-work evidence + mechanism closure
   │
   ▼
R4/R5 独立 Rust kernel（新入口、新状态布局、版本化协议）
```

- **Python 是语义参考和现网实验场**，不是 Rust 的性能或内部 API 约束；没有用户数据迁移要求。
- **共享向量锁定不变量，不锁定 Python 细节**：安全拒绝、终态、防重入、审计因果和保留 wire
  字段必须有证据；dict 顺序、异常文本、singleton 和 reaper 时序可以重设计。
- **Rust-first 优化以证据驱动**：优先优化实测串行/队列/锁瓶颈，但最终内核可以采用与 Python
  完全不同的所有权、调度、内存和持久化模型。
- **前端 TS、Rust kernel、Python 参考三者解耦**：仅对明确保留的协议边界维持版本化 wire contract。

### 4.5 “完整翻译”的限定定义与递进顺序

后续可以把所有**符合 Rust 边界的 L1 机制**逐步重建，但这里的“完整”不是把
`systems/python-reference-runtime/l1/kernel/` 的每个 Python 文件机械搬运。保持不变的是经过 R0 确认的安全/控制不变量和
明确保留的 wire contract；Rust 内部可以采用不同的数据结构、并发模型、状态目录和错误分类。

递进顺序固定为：

1. **契约层**：Process/Event/Capability 等纯值类型、序列化规则和 golden vectors。
2. **并发机制层**：sync、channel、EventBus；先冻结公平性、所有权、过载丢弃和取消语义。
3. **进程机制层**：ProcessTable、生命周期 FSM、取消 token、owned handles。
4. **资源与执行门层**：allocator、worker、gatechain、`invoke_capability`、持久审计。
5. **系统机制层**：IPC、checkpoint/restore、versioning、路径/platform seams，以及有证据
   支持的 process/fs adapters。

每个模块都必须通过语义不变量 vectors、Rust-native stress/performance evidence 和
明确的 cutover/recovery 触发器；一个模块未达标不能进入独立 Rust kernel，也不能把上层策略
（prompts、skills、model/provider、cards、DVG、R5/Mer、AgentLoop 的策略与执行）移入 Rust；
逻辑路由候选必须单独通过 identity/session/terminal correlation 证据。

这一定义允许最终完成机制层的 Rust 实现，同时避免把 Python 的偶然行为或用户数据格式带入新内核。

当前分支的增量证据：Rust `worker` 候选已完成一个隔离切片（bounded
queue、FIFO 淘汰、结果句柄、panic 结构化失败、优雅 drain、idle shrink），
并补齐 `TaskHandle` 的 pre-start cancellation 与显式 task deadline；取消或
排队过期的任务以结构化 `Cancelled`/`TaskTimeout` 结束且不执行闭包，已运行
闭包不被强制中断，超时只在 worker 边界完成后判定。调用方等待超时仍是
独立的 `Timeout`。它仍未接入 `WorkerPort`、boot 或任何运行时执行权威；
adaptive sampling 与 Python 异常映射仍是 G6 前置决策。worker snapshot
同时提供 cancelled/timed-out/failed outcome counters，并在释放结果句柄前
完成计数更新，避免完成观察与统计读数竞态。

本轮执行主机切片将 runtime 的已拥有 WorkerPool 与 `KernelScheduler` 的状态所有权
分离：`dispatch_direct`/`complete_direct`/`stop_direct` 只更新 generation-safe
状态，不重复走 scheduler work queue，因此固定工作路径不会产生二次入队/出队计账。
若 worker 在 wrapper 启动前因淘汰、关闭或 admission 失败返回终态，`RuntimeTask::result()`
会主动收敛 direct scheduler 状态，任务仍可安全 `reap`；observer wait timeout 不会
误改任务状态。该行为由独立 runtime/scheduler integration targets 覆盖，且
`tests/infra/test_rust_test_domain.py` 门禁禁止 `systems/rust-kernel-engine/l1-kernel-rs/src/**/*.rs` 重新出现 inline tests。
这仍只是 R1/R2 候选优化和证据闭环，不改变 Rust kernel 尚未接管 boot、AgentLoop 执行、
Provider 或生产入口的边界。

当前新增的 `agent_loop` 片是 R3/R4 前置逻辑路由候选：`AgentLoopBook` 固定
agent/cell/session/terminal correlation，显式管理 Created/Ready/Running/Paused/
Closing/Stopped/Failed 生命周期，并在同一 loop 锁下把 input/event admission 交给
Rust `Session` 的 authoritative `input_seq`。它不执行 LLM/provider/tool，不改 terminal
mailbox，不启动 PTY/subprocess，也不拥有 WorkerPool；后续 TS bridge 可直接消费其
版本化 snapshot/receipt。该片通过独立 `tests/session/kernel_test_agent_loop.rs`，仍需与 runtime、protocol、
cutover/recovery 逐步闭合后才可进入新内核 authority。

该片的统一 v3 routing 基准（4096 items，1/2/4 workers，3 rounds）在当前未固定主机上、
采用 contention-only wait probe 后，测得逐输入中位吞吐约
1.819M/0.761M/0.760M ops/s，中位 contended loop-lock wait 约
0/5.011/13.583 ms，全部样本无错误/拒绝。它仍将共享路由锁列为下一优先级优化对象，
不把增加 worker 数或接入 runtime 当作默认策略。

随后完成 `agent_loop_execution` bridge 前置：`AgentLoopExecutionBridge` 将已启动
loop 的输入排入 `KernelRuntime`，任务在 worker 真正执行后才完成 input admission，
把 receipt/loop identity 交给调用方 action，并可将一个返回的 event 写回 Session。
报告和失败值固定版本与 admission/action/event-admission 阶段；pre-execution cancel
不产生历史写入，action failure 保留已提交 input receipt。该片只闭合 Rust-native
AgentLoop/WorkerPool/Session 机制，不接 provider/prompt/tool/PTY，不做副作用 rollback，
也不授予生产入口或 R4/R5 cutover authority；独立测试位于
`systems/rust-kernel-engine/l1-kernel-rs/tests/runtime/kernel_test_agent_loop_execution.rs`。下一步仍需真实 host
adapter、进程组信号/PTY、生产 reaper、持久化执行失败策略和 TS/L2 消费协议评审。

随后补齐 AgentLoop 批量执行准入：`AgentLoopExecutionBridge::submit_input_batch`
在 worker 开始前通过一次 `KernelRuntime::submit_batch_strict` 预留整个请求组，容量不足时
严格 worker queue 也拒绝无法完整保留的批次并回滚所有 runtime task，因此不会留下部分
input history，也不会淘汰已有排队工作；已接受的成员仍分别执行
action/event admission 并保留独立 receipt 和失败阶段。空组是无副作用 no-op，独立
测试覆盖容量回滚、身份预检与成功批次。该切片只优化 Rust-native
AgentLoop/WorkerPool 边界，不引入 provider、PTY、进程副作用或生产 runtime authority，
后续仍需持久化执行失败策略与 TS/L2 只读消费协议。

随后已完成 IPC 与持久化机制切片：Rust `ipc` 覆盖 `LockMessage`、
`LockChannel`、`LockBus` 的有界历史、handler、request/response、超时清理和
reset；Rust `persist` 覆盖 `{seq,event,payload,ts}` 事件行、批量追加、过滤查询、
序列校验、重开恢复和 durable flush。随后完成了 `audit`/`capability` 切片：
`AuditLog` 提供有界按身份查询、detail 截断和可选 journal 接线；
`CapabilityAuthority` 对未接线调用 fail-closed、将 executor panic 转为结构化失败，
并为每次调用记录审计；该切片阶段通过 54 项 Rust 测试、51 项 Python
IPC/持久化回归通过。IPC 仍未接入 socket/跨进程所有权，持久化仍使用候选 JSONL
而非 Python SQLite，replay/checkpoint 策略仍由 Python 适配器持有；审计与能力候选
同样未接入 boot、Port 或生产执行路径。

下一片允许的机制工作是 Rust GateChain 候选：先冻结 G1-G5 的纯值输入、
有界历史 ledger 和 `PASS/WARN/BLOCK/REPORT` 结果，再补 Python/Rust vectors。
GateChain、Constitution、reputation、posture 和 approval provider 仍保持策略/适配器
归属，不得由候选自行发现工具或改变生产授权。

GateChain 纯机制候选已完成：Rust `gatechain` 消费显式 request/policy 快照，覆盖
G1 whitelist fail-closed、G2 interactive/process identity、G3 territory+danger+frequency、
G4 pre-approved/full-power/harness authorization、G5 reputation/history，以及有界
ledger 和结构化四态步骤；该切片阶段通过 61 项 Rust 测试与 Python 51 项参考回归，但没有
接入 boot、Port、posture/reputation provider、事件副作用或生产执行权威；共享 policy
fixture 已覆盖稳定的 block/pass 分支，再评审纯 Constitution 规则层。

随后完成 Constitution 纯规则候选：Rust `constitution` 提供 MUST/SHOULD/MAY
规则描述、动作分类索引、PASS/WARN/BLOCK 报告、territory/sandbox/constitution
文件保护、scout/cross-territory、GateChain 标记和显式 offensive-skill posture 输入。
它的规则测试通过 67 项 Rust 测试；Markdown/SettingsCenter、NMI/EventBus、skill/posture provider
和 runtime routing 仍由 Python 持有。共享 fixture 已在 Python/Rust 两侧通过；下一步
是冻结规则序列化与自定义规则策略，再进入 G6 选择性 pilot 评审。已知 Python
`write_file` action-category 缺口保持为独立参考实现问题，本片不隐式修复。

当前 policy parity 门禁总量为 69 项 Rust 测试、52 项 Python 参考回归；该数字随
候选切片和 fixture 扩展更新，不代表任何 Rust runtime authority 已启用。

随后完成 Rust VFS 机制候选：`vfs` 提供有界 MountTable、最长前缀
`resolve_mount`、ring/只读权限判断、虚拟文件存储、provider-read TTL 缓存与
失效，以及结构化 `ENOENT`/`EACCES`/`EROFS`/`EADAPTER` 错误。真实文件、
`/proc`、`/sys`、`/skills`、`/dev` provider 与写入适配器仍由 Python 持有；Rust
候选对非虚拟操作 fail-closed，不访问 OS，也没有接入 Port、boot 或生产路径。
该切片新增 9 项 Rust 测试（含 Python/Rust 共享挂载解析 fixture），工作区总数为 79 项；它不是 policy parity 数量，
不会解除 G3/G6，也不改变 Python 默认运行时。

随后完成 Rust 生命周期与 schema 迁移机制候选：`lifecycle` 覆盖
`halted/installing/booting/active/draining/crashed` FSM、checkpoint record、
boot/shutdown bookkeeping 与 install/recovery 判断；`versioning` 覆盖 Python
当前实际注册的六类 schema、ordered JSON migration、future/missing/failure
错误；`migration` 覆盖 install-time ordered runner、target bound、first-error
stop 和 panic 结构化。Python/Rust 共享
`kernel_lifecycle_vectors.json` 与 `kernel_versioning_vectors.json`，Rust
workspace 测试总数达到 117 项，双侧 fixture 均通过；重复版本 migration 的注册顺序也已在
Python/Rust 两侧回归锁定。该片仍不读写真实文件、
不接 boot/Port、不拥有 timestamp/settings/provider 侧效应，也不会解除 G3/G6。

随后完成纯算法 `load_adaptive` 候选：Rust 镜像 EWMA、hysteresis、目标区间
HOLD、GROW/SHRINK 限幅、慢任务 `GROW_FAST`、cooldown、reset 和稳定 reason；
`kernel_load_adaptive_vectors.json` 在 Python/Rust 两侧通过，Rust workspace
测试总数达到 119 项。时间由调用方显式传入，采样、WorkerPort 扩缩容、线程和
`LOAD_ADAPTIVE_ENABLED` 仍由 Python 持有；该候选不接入 worker、boot 或 Port，
也不解除 G3/G6。

随后完成 `schema` 字符串事件注册表候选：Rust 镜像 owner 冲突拒绝、同 owner
幂等更新、排序快照、membership 与 reset；共享 `kernel_schema_vectors.json`
在 Python/Rust 两侧通过，Rust workspace 测试总数达到 122 项。L3 catalog、boot
注册和事件发射仍由 Python 持有，候选不接入 EventBus、boot 或 Port，也不解除 G3/G6。

随后完成 `rule_descriptor` 纯值候选：Rust 镜像 MUST/SHOULD/MAY、PASS/WARN/BLOCK、
描述元数据、排序 tags、显式 created_at 和 checker context；共享
`kernel_rule_descriptor_vectors.json` 在 Python/Rust 两侧通过，Rust workspace
测试总数达到 124 项。规则 catalog、Markdown/SettingsCenter、Constitution provider
和 runtime policy 仍由 Python 持有，候选不接入 boot、EventBus 或 Port，也不解除 G3/G6。
规则描述器的 checker 返回 `None` 仍按 PASS 处理，但 callback panic 会被捕获并
转换为 BLOCK，避免策略异常穿透 L1 或意外放行；该值层保护不接管
Constitution provider、Markdown/SettingsCenter 或生产 policy routing。

随后完成 `registry_base` 声明式注册基座候选：Rust 镜像 descriptor 默认值、重复
拒绝与显式覆盖、注册顺序、分类过滤、公开序列化和 register/unregister 统计；共享
`kernel_registry_base_vectors.json` 在 Python/Rust 两侧通过，Rust workspace 测试总数
达到 127 项。handler 闭包、领域 registry、发现/boot 注册和 runtime routing 仍由
Python/适配器持有；该候选不接入 Port、boot 或生产执行权威，也不解除 G3/G6。

随后完成 `registry_base` 热路径切片：内部改为 hash index + 显式 order vector，重复注册与
`get` 不再扫描整个 descriptor 列表，覆盖不改变注册位置，公开列表/分类视图仍保持注册顺序。
独立 `registry_base` 测试覆盖覆盖、删除和 clear 后的顺序不变量；`registry.base.lookup` runner
按 4096 items、1/2/4 workers、3 rounds 输出统一 v3 吞吐、p95/p99、CPU/RSS 证据。一次本地
release 样本的派生吞吐中位数约为 1.51M/1.52M/0.90M ops/s，零拒绝/错误；该数字仅是候选
基线，不代表相对旧 Vec 的稳定提升，需同规格旧实现对照后才可推进策略升级。handler 闭包、
领域 registry、发现/boot 注册和 runtime routing 仍留在 Python/适配器边界。

随后完成 `identity_uid` 值边界候选：Rust 镜像前缀/长度校验、调用方注入的熵候选、
有界碰撞重试、已存在 UID 追踪与 reset；共享 `kernel_identity_uid_vectors.json` 在
Python/Rust 两侧通过。随机熵、持久化 binding 和身份签发权威仍由 Python 持有；该候选
不接入 boot、Port 或身份服务，也不解除 G3/G6。

随后完成 `device` 记账候选：Rust 镜像显式设备记录、滑动窗口限流、严格 degraded/down
阈值、调用计数、摘要和聚合统计；共享 `kernel_device_vectors.json` 在 Python/Rust 两侧
通过。SettingsCenter 默认值、外部 provider 连接、健康线程和系统时钟仍由 Python 持有；
该候选不接入 boot、Port 或 provider，也不解除 G3/G6。

随后完成 `bus` 依赖规划候选：Rust 镜像 `ComponentMeta` 默认值、重复注册原位覆盖、父总线
可用依赖过滤、稳定 Kahn 拓扑排序、周期拒绝和显式注册/初始化/启动/停止状态标签；共享
`kernel_bus_vectors.json` 在 Python/Rust 两侧通过。事件 handler、子总线广播、健康/统计 provider、
日志与实际生命周期副作用仍由 Python 持有；该候选不接入 boot、Port 或 SystemBus 运行时权威，也不解除 G3/G6。

随后完成 `resource` 限额候选：Rust 镜像 `ResourceLimiter` 的注入 profile、fallback 查询、带符号
check/release 记账、usage/all_usage、未知资源处理与 cleanup；共享 `kernel_resource_vectors.json`
在 Python/Rust 两侧通过。角色配置发现、allocator 的 OOM 回收、线程/进程副作用与持久化仍由 Python
持有；该候选不接入 boot、Port 或执行权威，也不解除 G3/G6。

随后完成 `health` 结果聚合候选：Rust 只接收显式 subsystem 状态映射和 elapsed 值，镜像
`DOWN`/`DEGRADED`/`OK` 优先级、healthy/degraded/failed 计数、详情保留与 elapsed 舍入；共享
`kernel_health_vectors.json` 在 Python/Rust 两侧通过。模块导入、系统时钟、单例探针、日志与运行时
provider 仍由 Python 持有；候选不调用 `safe_system_check()`，不接入 boot、Port 或生产健康权威，也不解除 G3/G6。

随后完成 `swapper` 规划候选：Rust 镜像显式 entry importance 的 ring-2/ring-3 路由、过期短环压缩
筛选，以及 allocator/memory 百分比驱动的压力动作标志；共享 `kernel_swapper_vectors.json` 在
Python/Rust 两侧通过。MemoryService 读写、allocator pressure 采样、时钟、后台线程与持久化仍由
Python 持有；候选不接入 boot、Port 或生产内存权威，也不解除 G3/G6。

随后完成 `registry` 值聚合候选：Rust 镜像寄存器 section 的名称排序与隔离快照，以及显式
模块健康计数、进程/设备/系统调用计数和调用方时间的 summary 聚合；共享
`kernel_registry_vectors.json` 在 Python/Rust 两侧通过。section 写入者、单例查询、系统调用发现、
时钟和 runtime registry ownership 仍由 Python 持有；候选不接入 boot、Port 或生产 registry 权威，
也不解除 G3/G6。

随后完成 `tool_chain` 指纹链候选：Rust 镜像调用字段规范化、HMAC-SHA256 截断、`GENESIS`
回退与 root-first 链完整性校验；共享 `kernel_tool_chain_vectors.json` 在 Python/Rust 两侧通过。
密钥生成/持久化、调用存储、裁剪重根和工具执行权威仍由 Python 持有；候选不接入 boot、Port 或
capability 执行面，也不解除 G3/G6。

随后补齐 `RWLock` parity 切片：共享 `kernel_sync_vectors.json` 固定重入读锁、零超时写锁失败、
状态快照和缺失 owner 解锁错误，Python/Rust 独立测试域均通过。随后 Rust 候选补齐 FIFO writer ticket、
超时 ticket 移除与 successor 唤醒；排队 writer 公平性已由 Rust blocking 回归固定。随后补齐独立
`cancellation` 原语：不可重置的 cloneable token、首因保留、协作式检查和有界等待，RWLock 在取消时移除
writer ticket 并唤醒后继。任务/队列取消、跨进程所有权和运行时锁路由仍是开放项。

随后补齐 EventBus 确定性 parity：共享 `kernel_event_vectors.json` 固定有界 history、按类型过滤、
signal 序列化和无 listener 时的 dispatch 计数，Python/Rust 独立测试域均通过。随后 Rust 候选补齐按
signal channel 的 FIFO 与跨 channel progress：同一 channel 同时最多一个 callback，worker 会跳过忙 channel，
慢 callback 不阻塞无关 channel；该调度不接入 Python executor、shutdown authority 或 SSE/WS fan-out。

随后补齐 `process` 生命周期 parity：共享 `kernel_process_vectors.json` 固定 PID/PCB 注册、
READY/RUNNING 往返、identity verified、取消后的 STOPPED 终态、exit→ZOMBIE→reap、tokens/cards/scouts/CPU
记账与去时间戳后的 audit 顺序，Python/Rust 独立测试域均通过。Python zombie reaper、interrupt 触发、
allocator/limiter 清理、长生命周期 OS handle 和运行时路由仍是适配器副作用，不纳入 Rust 候选契约。
随后补齐 `ProcessTable` 的 typed-handle bridge：live PID 在 substrate slot 范围内映射为
generation-one `ProcessHandle`，stale generation、exit 后和 reap 后的 handle lookup 均 fail-closed；
可复用 slot 的 generation ownership 仍由 `state_queue` 持有，避免把 parity table 误当成新内核 runtime authority。

R1 已启动：Rust `substrate` 提供 generation-tagged process handle、确定性 shard plan 与无 JSON
分配的 atomic queue metrics，`benchmark` 提供固定总量报告 schema；它们只冻结所有权/观测基元，
不接管 ProcessTable、调度、boot 或运行时路由。`state_queue` 已提供分片 slot map、代际校验、
终态转换和 fail-fast 有界队列，并提供 token-aware pop：取消在出队前返回 `Cancelled`；
`benchmark_runner` 已提供固定总量 contention smoke，覆盖
worker/round 完整性、p95/p99、队列/admission 等待、拒绝计数和 process CPU/RSS 资源采样，统一
使用纳秒、字节和显式 source/unavailable 标记，吞吐由固定完成量与墙钟时间推导。
`reputation` 已提供显式策略注入的 G5 分数 ledger，但 singleton、持久化、provider 和 GateChain
路由仍在适配器侧；`notify` 已提供显式时间戳、有界保留、最新优先查询和 drop 计数的旁路
buffer，但 EventBus/SSE/WS/webhook 投递仍在适配器侧。`BenchmarkEvidence` 已提供带 schema、平台、架构、
runtime、revision、runner 和 resource-unit 归属的完整 JSON 导出，`make rust-benchmark` 可重复生成 Rust
queue contention 证据；`make r2-baseline-bundle` 进一步以独立 Python reference 运行同一 fixed-work 规格，
校验两侧样本矩阵并生成对照 bundle；`make r2-baseline-analysis` 再按 worker 汇总吞吐缩放效率、p95/p99、
拒绝/错误比例、队列/锁等待和资源中位数。该片完成 R2 测量与描述性分析脚手架，但不作性能切换决策，也不授予新内核运行时权威。
随后对 `state_queue` 完成 Rust-native 热路径优化：默认 try admission 的 consumer 使用 bounded batch drain，
减少队列锁获取；`PRAXIS_RUST_QUEUE_MODE=blocking` 仅作为条件变量背压对照。当前实测 blocking 在多 worker
下出现 convoy 和 p95 恶化，因此不改变默认策略，也不授予 runtime authority。
随后将 bounded drain 的 completion 记账收敛为单次原子计数更新与饱和 depth CAS，固定工作量完成数、重复完成
下溢保护和 v3 证据字段保持不变；`process`、`terminal`、`benchmark_runner` 的机制测试同步迁移到
`systems/rust-kernel-engine/l1-kernel-rs/tests/<domain>/` 分域独立测试域，Cargo 保持历史 target 名并显式登记路径，
为后续 TS/Rust 重写保留清晰的公共 API 边界。
对 producer claim-batch 的同规格实验因 4-worker 中位 tail latency 回退而不纳入默认实现；性能改动必须同时
通过 1/2/4-worker 的 fixed-work 吞吐和 p95/p99 证据，不能以单 worker 加速替代整体基线。
随后重复比较 consumer batch 32/64（每种三次、同一 4096×[1,2,4]×3 fixed-work 规格）：batch 64 的中位吞吐
在三个 worker 点均回退约 9.1%/1.6%/3.6%，p95 也回退，因此保留 batch 32；单点 p99 改善不构成合入依据。
随后将 `worker` 的 8 项实现内行为测试并入已有独立 worker target，扩缩容回归改为只通过公开提交、结果与
shutdown 观察，避免为测试暴露私有 `add_worker`；该片共 10 项 worker 测试分片通过。
随后将 `WorkerPool` 的 Metrics 从全局互斥锁改为原子计数：提交拒绝、active/completed/outcome 和 pool-size
读写不再让每个任务争用同一 accounting lock，队列与 worker join list 仍保留必要的 mutex 所有权。独立
`tests/core/kernel_test_worker.rs` 增加并发提交不变量，验证 completed + evicted 等于固定提交总量；该优化仅改变计账机制，
需继续用 fixed-work tail-latency 证据决定是否进入最终 runtime policy。
为避免把 lower-level queue contention 与执行主机成本混在一起，新增 `worker.pool.batch` 专项 runner 与
`rust-worker-bench` release binary：固定 4096 items、1/2/4 workers、3 rounds，queue capacity 必须覆盖总量，
因此 eviction 不会被误算为吞吐。当前本机首轮完整样本均为 errors=0/rejected=0，但 2/4 worker 吞吐低于 1 worker，
后续优先优化 task handoff/queue，而不是继续放大 metrics 计账优化的结论。
随后移除 worker completion 后仅用于检查空队列的冗余 mutex 获取：最后一个 active 计数递减负责唤醒
drainer，shutdown 仍同时检查 queue depth 与 active count 后再 join。worker target 重复运行 10 次通过，
该片减少每任务一次队列锁竞争，仍需纳入后续 fixed-work tail-latency 测量。
随后将 worker claim 改为有界批次：每次队列锁最多领取 8 个 FIFO 任务，并复用本地缓冲；`active` 覆盖已领取但
尚未完成的任务，避免 shutdown 在本地批次任务之间误判 drained。worker/runtime/benchmark 分片通过，固定
4096 项 release smoke 仍为 0 error/0 rejection，但 2/4 worker 受 handoff/共享队列限制，批次仅作为候选优化，
不提升为默认扩缩容策略。下一优先级转向 R4/R5 的真实入口与 adapter closure，而不是继续堆叠微优化。
随后补齐 WorkerPool 性能证据的 `queue_wait_ns`：每个 worker 只在批次领取成功时累计从 claim 开始到领取完成的
等待，避免每任务计时造成额外热路径开销；`run_worker_pool_batch` 不再把该字段固定为 0。当前 4096 项 release
扫测的中位 claim wait 约为 1.0/19.7/177.8 ms（1/2/4 worker），与 1.20M/339K/88K ops/s 吞吐相互印证，
说明共享队列 handoff 是当前扩展瓶颈。后续队列方案必须在同一固定总量 schema 下同时改善吞吐、p95/p99 和 queue wait。
随后新增 `WorkerPool::submit_result_batch` 批量 admission 候选：一次持有队列锁，仍按 FIFO
执行 oldest-pending eviction，并为关闭池、取消和结果句柄保留逐项完成语义；现有单任务 deadline
边界不被绕过。新增独立 `worker.pool.batch_submit` runner、`rust-worker-batch-submit-bench`
入口及 `tests/core/kernel_test_worker.rs`、`tests/runtime/kernel_test_benchmark_runner.rs` 覆盖，Rust 实现文件不含测试块。
同规格 release 重复采样（4096×[1,2,4]×3，batch size=32）中位吞吐约为 1.66M/3.85M/4.19M
ops/s，逐任务 baseline 约为 1.20M/0.28M/0.07M ops/s；batch-submit queue wait 约为
0.09/0.18/1.21 ms，baseline 约为 0.96/24.40/210.48 ms，双方均为 0 error/0 rejection。
该数据支持 admission 优化候选，但 batch p95/p99 是批次级分布，不能直接替代逐任务尾延迟，仍需
在统一量化标准下持续对照后才能进入 runtime policy。
随后将 WorkerPool 的唤醒边界收窄为实际处于队列等待的 idle waiter：等待计数在 queue lock 内登记，
producer 只对当前 waiter 发 `notify_one`，活跃 worker 不再承担无效唤醒调用。该计数仅是唤醒优化，
不是正确性依赖；shutdown 仍使用 `notify_all`，FIFO、claim batch、取消和 drain 语义保持不变。需在同一
fixed-work 吞吐、p95/p99、queue-wait 矩阵中复测后，才能决定是否提升为 runtime policy。
随后将单任务 `submit_result` 的准入返回改为 typed outcome，直接完成 `TaskHandle`，跳过中间
`WireMap`/JSON 构造与解析；fire-and-forget 的 wire 响应保持不变。拒绝、淘汰、取消、deadline 和 shutdown
完成语义不变，仍需在统一 fixed-work 证据门下复测，不能仅凭局部微基准提升为 runtime policy。
随后将 `TaskHandle::done()` 改为读取 release-published 原子完成标志，轮询不再争用结果互斥锁；
结果值复制与阻塞等待仍由原有同步槽和 Condvar 负责，完成顺序与错误值不变。该片仍需统一 fixed-work
证据复测，不单独作为 runtime policy 依据。
随后在 `state_queue` 增加 `ProcessHandleAllocator`：Rust 侧以有界 slot、释放代际递增、旧 handle 拒绝和
容量/重复释放 fail-closed 固定可复用身份候选；该候选暂不替换 generation-one `ProcessTable` bridge，也不
接管调度或 boot authority。
随后新增 `scheduler::KernelScheduler` candidate，组合 generation-safe slot、分片 lifecycle state 与 bounded
typed work，固定 queue-full rollback、stopped work discard、spawn/schedule/claim/complete/stop/reap 语义；该片
不启动 worker thread、不执行 boot callback、不接管 AgentLoop 或 provider authority。
随后新增 `runtime::KernelRuntime` candidate，组合 locked assembly、lifecycle FSM、`KernelScheduler` state ownership 与
bounded WorkerPool，固定 halted→booting→active、submit、任务状态、取消、deadline、reap 和 clean drain shutdown；
该片只接收已绑定 Rust closure，不接入 Python/FFI、PTY/subprocess、AgentLoop 路由、provider 或生产入口，R4/R5
cutover/recovery 与 G6 仍是后续硬门；`open_persistent` 已将 `StateStore` 接入同一生命周期，覆盖 fresh-root
checkpoint、clean resume 与 unclean recovery，但不导入 Python 状态，也不改变默认生产路径。
`submit_gated` 同步接入 Rust G1-G5 与单一 `CapabilityAuthority`，caller/tool 不匹配、空 whitelist 或未接线
executor 均在进入 worker queue 前 fail-closed 并记审计；真实 tool pipeline/provider 仍留在适配器。
随后补齐 `KernelRuntime::reap_finished(max_tasks)`：按调用方预算选择 task handle，只回收已确认 terminal 的任务，
并返回 `pending/unavailable/errors` 计数；零预算 fail-closed。该接口不启动后台 reaper、不改变 lifecycle，
仅为后续 shutdown/recovery ownership 提供有界机制候选。当前选择阶段在单次 shard 锁内同时快照 handle 与
runtime state，移除逐 handle 的二次加锁/查表；若状态在选择后才终止则保守记为 pending，并发 reap 则记为
unavailable，稳定 shard/BTree 顺序与预算上限不变。
随后完善 `KernelRuntime` 的并发 admission：以 lifecycle `RwLock` 的共享侧覆盖 active-state 校验、handle
reservation、按 scheduler shard 划分的 task-book 登记和 WorkerPool handoff；boot 使用独占侧，shutdown 先发布
`Draining` 再取得独占侧排空已准入任务。任务在
`dispatch_direct` 之前登记，避免极快 closure 先写 terminal state 又被晚到的 `Ready` 覆盖。`submit_observed`
仅在 `try_read` 或 task-book `try_lock` 真实阻塞时采样；普通 submit 不读取时钟也不更新计数。独立
`runtime.submit_reap` runner 与 `rust-runtime-bench` 固定每个 caller 每次只 submit/wait/reap 一个已绑定 Rust closure，
因此不把 eviction policy 混入量化。基于对齐主树 `06e8288c` 的 Linux x86_64 release、4,096 项、1/2/4 worker、各 3 rounds
全部为 0 error/0 rejection；中位吞吐约 18.1k/27.3k/32.1k ops/s，p95/p99 约为 85/140、232/562、600/1,342 microseconds，
WorkerPool aggregate claim/wake wait 为 155.2/262.8/469.7 ms，而 runtime admission 的中位 contended wait 为零。
这只证明 admission 串行化不再是当前瓶颈，下一性能候选是 WorkerPool handoff 与 tail behavior；不构成 scaling policy、
L2/TS wire、AgentLoop、Provider、PTY 或生产入口权威，也不改变 clean-break Rust 内核不兼容 Python 用户状态的路线。
下一批量 admission 片新增 `submit_batch`/`submit_batch_observed`：在一次 WorkerPool grouped handoff 前预留并登记全部
generation-safe handle，任一 reservation 失败即 rollback 先前全部 reservation，保证 closure 尚未执行。独立
`runtime.batch_submit_reap` 与 `rust-runtime-batch-bench` 让每个 caller 每次只 submit/wait/reap 一批，并把 process/queue
capacity 设置为最多同时在途批次数，避免将 eviction policy 混入量化；completed work/throughput 仍按 task，p95/p99 则严格按
complete batch 报告，禁止与单任务延迟混比。一次 Linux x86_64 未固定主机、batch=32、4,096 项、1/2/4 caller、各 3 rounds 的
release 样本全部 0 error/0 rejection：中位吞吐约 363k/540k/591k tasks/s，aggregate WorkerPool claim/wake wait
约 5.4/8.7/18.7 ms，observed runtime lock wait 约 0/0.086/0.045 ms，batch p95/p99 约为
151/218、217/290、442/586 microseconds。同一对齐树独立单任务复测约为 18.1k/27.3k/32.1k tasks/s、queue wait
155.2/262.8/469.7 ms；该未固定本地对照只支持保留 grouped-admission candidate，不宣称线性扩缩容、tail win、L2/TS wire、
AgentLoop、Provider、PTY 或 production/cutover authority。
随后将 `state_queue` 的 9 项实现内测试迁移到独立 target；其分片覆盖 shard transition、FIFO/backpressure、
取消等待、batch accounting、allocator reuse 和并发插入，源模块不再保留测试块。
随后将 `substrate` 的 4 项和 `benchmark` 的 7 项机制测试迁移到独立 target，覆盖 generation handle、shard
plan、atomic queue metrics、fixed-work schema、资源来源校验、完整样本矩阵与 evidence round-trip；同时将
crate contract-version 检查归入 `contract_vectors.rs`，`lib.rs` 不再保留内联测试。该片只改变测试域组织，
不改变候选实现或运行时权威边界。
随后将 `health` 的 2 项、`territory` 的 3 项和 `registry` 的 1 项公共行为测试迁移到独立 target，覆盖共享
向量、状态聚合、组件感知路径边界、显式 working directory 和空输入确定性；这些切片仍不读取 provider、时钟
或 filesystem，也不改变 Rust candidate 的运行时权限。
随后将 `identity_uid` 的 2 项、`swapper` 的 2 项和 `tool_chain` 的 2 项纯值行为测试迁移到独立 target，覆盖
候选 UID 的去重/重置、Memory ring swap/pressure 规划、GENESIS fingerprint 链和篡改拒绝；身份持久化、
MemoryService I/O、工具执行与链存储仍留在后续 adapter/runtime 阶段。
随后将 `schema` 的 3 项与 `migration` 的 4 项测试迁移到独立 target，覆盖 owner 冲突、共享 schema 向量、
全局 reset、排序/目标版本边界、失败短路、panic 结构化和重复版本注册顺序；它们仍是候选注册/安装机制，
不读取生产配置、不执行真实迁移副作用，也不接管 boot authority。
随后将 `capability` 的 4 项测试迁移到独立 target，覆盖未接线 fail-closed、调用审计、executor 错误/ panic
结构化和全局 authority reset；该候选仍不接入真实 GateChain、tool pipeline、provider executor 或持久化审计。
随后将 `cancellation` 的 3 项、`notify` 的 3 项与 `reputation` 的 4 项机制测试迁移到独立 target，并保留
reputation 向量 target；覆盖首因/clone wake-up、bounded newest-first drop/reset、score clamp/delta 和
非有限输入拒绝。旁路发送、持久化、provider 与 G5 GateChain routing 仍留在适配器阶段。
随后将 `audit` 的 3 项、`device` 的 1 项、`interrupt` 的 3 项和 `errors` 的 3 项测试迁移到独立 target，
覆盖 bounded journal/query、device rate-health 向量、IRQ history/sequence 和 structured error/trace 向量；
EventStore、设备 provider、IRQ callback 和 trace adapter 仍不由 Rust candidate 接管。
随后将 `channel` 的 5 项、`bus` 的 2 项和 `registry_base` 的 3 项机制测试迁移到独立 target，并保留 channel
向量 target；覆盖 FIFO/overwrite/backpressure、close/drain waiter 唤醒、依赖拓扑/生命周期和 callback/公开
metadata 视图。socket/IPC、组件 callback side effects 和 domain registry authority 仍留在 adapter 层。
随后将 `event` 的 7 项机制测试迁移到独立 target，并保留 event 向量 target；覆盖 typed/wildcard dispatch、
bounded drop、动态 signal registry、shutdown、同 channel FIFO 和 busy-channel 跨 channel progress。真实
EventBus 外部 fan-out、SSE/WS、provider callback side effects 和 runtime ownership 仍在适配器层。
随后将 `load_adaptive` 的 3 项和 `versioning` 的 6 项机制测试迁移到独立 target，覆盖控制律 reset、EWMA/
hysteresis/cooldown、六类 schema stamp、ordered migration 与 fail-closed 错误；源模块不再保留内联测试块，
调用方时间、settings/provider 侧效应和 runtime worker ownership 仍留在适配器层。
随后补齐 `channel` 机制切片：共享向量锁定 FIFO、满载零超时拒绝、overwrite-oldest、关闭后排空与
利用率语义；Rust 候选的 `drain` 在释放容量后唤醒全部等待生产者，避免多生产者下的虚假低利用率。
该片仍只覆盖 JSON 边界原语，不接入 socket、IPC transport、AgentLoop 或生产 runtime authority。
随后封口 `constitution` 自定义规则快照：Rust 对 ID/source/kind 做 fail-closed 校验，归一化 tags，拒绝重复
ID 且失败替换保留旧快照；共享 `kernel_constitution_vectors.json` 只冻结规则元数据，不接管 Markdown、姿态
provider 或生产 policy routing。
`identity_binding` Rust candidate 已收敛 `(cell, role)` 元数据、
fail-closed 写门、Cell 容量、UID rebind 稳定性、revision 与确定性 snapshot。
随后新增 `IdentityBindingStore` R4 元数据持久化切片：采用版本化
`BindingCheckpoint`，只写入 bounded identity-routing metadata，在完整校验后以
唯一临时文件原子替换，并在写失败时恢复内存 checkpoint；prompt/definition、
Python persistence bytes、跨进程锁、事件和 API/L2Shell 仍由适配器持有，
不能作为 Python registry 的兼容迁移。
随后新增 `network` Rust candidate，已收敛 caller-clocked PeerBook 的 endpoint 校验、self-ignore、timeout、
loss-once、eviction grace 与 deterministic health/list；TCP/UDP/TLS、socket、EventBus、card sync 和 message
envelope 仍留在 transport adapter，不授予 Rust runtime authority。
随后新增 `boot` assembly candidate：Rust `BootPlan` 只负责 step metadata、显式 replacement、锁定和确定性
dependency-first 拓扑排序；重复步骤、无效名称、缺失依赖和循环依赖均 fail-closed。共享
`kernel_boot_plan_vectors.json` 在 Rust/Python 两侧通过，并显式记录 Python 对缺失依赖的历史忽略行为。
该片不执行 callback、不读配置、不启动线程、不改变 lifecycle、不接入 Python boot registry，也不解除 G3/G6；
R4 仍需独立 Rust-owned config/state layout 与 versioned protocol boundary。
随后新增 `state_layout` R4 前置 candidate：Rust 定义全新的 versioned manifest、canonical relative entries 与
parent-directory coverage，并将显式 host probe 归约为 `initialize/resume/recover/migrate/reject` 决策；共享
`kernel_state_layout_vectors.json` 在 Rust/Python 两侧通过。该片不创建目录、不读文件、不导入 Python 状态、不执行
migration callback；filesystem probe 与 side effect 仍由后续 R4 adapter 持有，也不解除 G3/G6。
随后新增 `ports` mechanism candidate：Rust 翻译 `PortResult`、`Endpoint`、`Message`、隐私保护的
`InputActivitySnapshot` 与确定性 `PortRegistry`；共享 `kernel_port_vectors.json` 在 Rust/Python 两侧通过。
注册重复、无效名称和锁后普通写入均 fail-closed，但该片不实例化 process/storage/lock/scheduler/transport/worker
或硬件输入适配器；具体副作用仍由后续 R4 Rust adapter 承接，也不解除 G3/G6。
随后将 `network` 的 3 项、`rule_descriptor` 的 2 项、`boot` 的 3 项和 `ports` 的 2 项机制测试迁移到独立
integration targets，并保留各自的共享 vector target；PeerBook、规则 checker context、BootPlan 拓扑和
PortRegistry/value 校验均只通过公开 API 验证，网络 transport、规则 provider、boot callback、provider I/O
与硬件输入采集仍由适配器持有。
随后补齐锁定后的 `BootPlan::execute` caller-owned seam：调用方必须提供与
依赖图完全一致的 `BootAction` map，执行器在首个 callback 前校验缺失/多余
handler，按 dependency-first 顺序执行，并在错误或 panic 时返回 completed
prefix。它不自动发现 provider、不推进 lifecycle、不做副作用 rollback，也不
授予 Rust production boot authority；这些策略仍由宿主适配器负责。
随后将 `identity_binding` 的 4 项、`state_layout` 的 3 项、`state_store` 的 5 项和 `config_store` 的 5 项
机制测试迁移到独立 target；filesystem-bearing 测试只使用临时 Rust-owned roots 并通过公开 API 验证，
prompt/persistence provider、Python state import、migration callback 与配置策略仍不进入 Rust runtime authority。
随后将 `platform` 的 3 项、`paths` 的 5 项、`discovery` 的 3 项和 `lifecycle` 的 6 项机制测试迁移到独立
target，覆盖 provider-neutral command/path 计算、三层 discovery merge、生命周期 FSM/checkpoint 与 reset；
命令执行、环境探测、YAML 扫描、时钟、持久化和 Python boot wiring 仍由适配器持有。
discovery 候选随后补齐 Rust 侧身份边界：section/key 的空白、NUL、长度和嵌套
对象键在写入前 fail-closed，文档合并采用 staged copy 一次提交，并提供确定性
snapshot/有序 section 读模型。该片只服务后续 TS/L2 读桥，不接管 YAML 扫描、
boot 注册或 Python registry 权威。
随后将 `contract` 的 5 项、`ipc` 的 6 项、`persist` 的 3 项和 `assembly` 的 3 项机制测试迁移到独立 target；
它们通过公开值/锁 IPC/JSONL journal/assembly snapshot API 验证，共享 vector target 继续保留，socket、SQLite、
多进程 replay、provider wiring、filesystem side effects 和 runtime authority 仍不进入候选内核。
随后将 `protocol` 的 5 项、`constitution` 的 7 项和 `gatechain` 的 8 项机制测试迁移到独立 target；
它们只通过公开 API 与共享 policy/protocol vectors 验证版本化记录、规则决策、G1-G5 步骤和 bounded ledger，
HTTP/WS、Markdown/provider policy、EventBus、approval/reputation routing 与生产授权仍留在适配器层。
随后将 `allocator` 的 6 项和 `vfs` 的 10 项机制测试迁移到独立 target；资源 profile/pressure/swap 与
mount/virtual-file/cache/provider-neutral fail-closed 行为只通过公开 API 验证，真实系统路径、进程终止、
Python allocator/VFS provider、SQLite persistence 和 runtime authority 仍不进入候选内核。
随后将 `sync` 的 11 项机制测试迁移到独立 target，并保留 `sync_vectors` 共享向量 target，覆盖
Mutex 重入/竞争/超时/优先级回调、Semaphore、Barrier、Condition，以及 RWLock writer preference、重入深度、
FIFO ticket、公平性和取消唤醒。该片移除 `sync.rs` 内联测试块，统一通过公开 API 验证；任务/队列取消、跨进程
锁所有权、deadlock-cycle 报告和生产运行时路由仍未完成，不授予 Rust runtime authority。
随后新增 `assembly` R4 seam：`KernelAssembly` 组合 `BootPlan`、`StateLayoutManifest`、`PortRegistry` 与 halted
lifecycle，独立 `rust-kernel` binary 要求宿主显式传入 state root，并可在无 Python/FFI 下输出确定性 JSON snapshot；共享
`kernel_assembly_vectors.json` 在 Rust/Python 两侧通过。当前仍不读配置、不创建 state root、不执行 callback、不实例化
provider；随后新增 `state_store::StateStore` filesystem adapter，按 manifest 创建全新 Rust root，
以临时文件 + `sync_all` + 原子 rename 持久化 manifest/lifecycle/checkpoint，并将 clean resume、unclean
recovery、分歧/迁移 root fail-closed 固定下来。该片仍不读取 Python 状态、不接管 Python boot/runtime，
也不解除 G3/G6；协议 v1 与配置存储已在独立 Rust 边界收敛。
随后封口 `StateStore` 的失败原子性：checkpoint generation 仅在 lifecycle 与 checkpoint
双写成功后提交；第二文件失败时恢复旧 lifecycle 字节，调用方可观察到的内存 lifecycle/generation
同时回滚，避免失败持久化后继续沿用脏代际。
随后补齐其异常根处理：缺失的旧 lifecycle 文件在失败 pair 中会删除新暂存文件，
回滚本身失败则返回显式 `RollbackFailed`，不再静默接受 split root；失败 rename
临时文件仍必须清理。
随后封口 runtime 的跨 store 关闭顺序：若 clean `ExecutionStore` 已写入而
后续 `StateStore` clean commit 失败，runtime 会先降级 execution checkpoint
为 unclean，再尽力写入 crashed lifecycle，避免重开时出现 clean execution
与失败 lifecycle 的 split-brain 配对。
随后补齐 `ConfigStore` 的跨文档失败边界：新增显式成对 config/setting
mutation，先完成两个文档的 staged 校验，再按 config→settings 原子替换；
第二个替换失败时恢复首个文档并清理临时文件，回滚失败显式 fail-closed。
独立 `kernel_test_config_store.rs` 覆盖内存、磁盘与临时文件清理；该片仍只拥有
Rust-owned JSON 根，不导入 Python 配置、不决定 engineering-debug 策略，也不提升为
R5 cutover authority。
随后将 `ConfigStore` 挂入 `KernelRuntime::open_persistent` 的 Rust-owned
运行时边界：`config_documents` 提供防御性快照，单文档与成对 mutation
通过 runtime owner 持久化后才返回；非持久 runtime 对配置访问 fail-closed。
持久化打开会先校验 assembly 选定的配置根与 execution checkpoint，再应用
unclean `StateStore` 恢复；foreign 或 malformed root 被拒绝时不会推进
recovery generation 或修改原有 lifecycle 记录。该片仍不热加载服务、不解释
Python settings，也不授予 R5 authority。
显式 checkpoint 与 recovery decision 读操作现在共享 runtime admission barrier；
shutdown 与 recovery acknowledgement 通过已持锁 helper 避免递归加锁，保证
生命周期变化不会穿过三本 book 的一致性观测。

随后推进 **R4 assembly closure + AgentLoop terminal substrate**：`KernelAssembly`
快照补齐 Rust-owned `ConfigLayoutManifest`、保留的 `ProtocolDescriptor` 与
`TerminalContractDescriptor`，配置/协议/终端版本或 assembly metadata 分歧均
fail-closed；独立 `rust-kernel` 入口输出完整确定性快照。新增 Rust
`terminal::TerminalBook` 作为上层 AgentLoop 的终端基础，只拥有唯一的
terminal/session/process 绑定；内部以 generation-tagged `ProcessHandle` 保存
进程身份，快照只在 wire 边界输出保留的 raw process id；同时提供
created/ready/running/stopped/closed 生命周期和
有界 opaque input/output mailbox（序号、背压、drop 计数）。PTY/subprocess、
AgentLoop 调度、提示词/工具策略、渲染、多前端 multiplexing 均留在后续 adapter/
L2/L3；`kernel_terminal_vectors.json` 仅在 Rust 独立测试域验证该机制，不形成
Python 数据兼容层，也不授予新内核运行时 authority。下一阶段转入 R2 固定工作量
性能基线，补 CPU、内存、queue/lock wait、p95/p99 与 reject/drop 证据。
随后新增 `protocol_host::ProtocolHost` 与 `rust-protocol-gate`：在进入未来
TS/AgentLoop bridge 前，以显式帧上限完成 JSONL v1 校验和 canonicalization；超大或非法帧
fail-closed，仅输出 stderr 诊断，不执行 command/intent、不持有 session、不授予 runtime authority。
机制覆盖位于独立 `tests/protocol/kernel_test_protocol_host.rs`，该片是 R4 protocol adapter 前置，不是 clean cutover 完成证明。
随后推进 P0 会话真值前置：新增 Rust `session::SessionBook`，采用分片 registry lock 与 per-session
message-id index，固定 bounded history、authoritative `input_seq`、monotonic message sequence、cursor
paging、created/active/closing/closed/crashed 生命周期和 versioned checkpoint/recovery。独立
`tests/session/kernel_test_session.rs` 与 `tests/session/session_vectors.rs` 覆盖并发 admission、分页、重复 ID、容量、崩溃恢复和
wire round-trip；实现文件不包含测试块。该片只提供未来 AgentLoop/TS bridge 的 session truth seam，
不接管 prompt/tool/provider/PTY，也不授予 Rust runtime authority。

随后补齐 P0 durable session store：新增 Rust `session_store::SessionStore`，将整个分片
`SessionBook` 以确定性排序的 versioned JSON 文档原子写入 Rust-owned
`snapshots/sessions/checkpoint.json`。clean shutdown 对 active/closing 会话 fail-closed；unclean
文档在载入时将非终态会话归约为 `crashed`，要求调用方显式 `recover`/`activate` 后才能继续写入。
该切片只读取新 Rust 状态根，不导入 Python 数据，不重放 AgentLoop/provider/tool/PTY 副作用；
`tests/session/kernel_test_session_store.rs` 独立覆盖 fresh、clean、unclean recovery、版本拒绝和原子文件边界。

随后补齐执行态的 R4/R5 恢复边界：新增 Rust `execution_store::ExecutionStore`，将
`SessionBook`、`TerminalBook` 与 `AgentLoopBook` 的 metadata 以一个 versioned、原子替换的
JSON 文档写入 `snapshots/execution/checkpoint.json`。它校验三本之间的 identity 引用和稳定排序，
clean checkpoint 拒绝 writable session、active loop/terminal、live process binding 与待处理 mailbox；
unclean checkpoint 将 session 归约为 `crashed`、loop 归约为 `failed`、terminal 解除进程绑定并归约为
`created`。不会持久化 PID/PTY 或 mailbox bytes，恢复必须由上层显式 rebind/recover；独立
`tests/session/kernel_test_execution_store.rs` 已覆盖 clean round-trip、unclean recovery、拒绝和版本错误。该片仍是
R4/R5 recovery seam，不授予 boot、Port 或生产 runtime authority。

随后将 execution checkpoint 接入 Rust `KernelRuntime` 的独立入口候选：runtime
现在拥有 `SessionBook`、`TerminalBook` 与 `AgentLoopBook` 三本元数据，持久化打开时从同一
Rust-owned root 的 `ExecutionStore` 恢复，显式 `checkpoint_execution(false)` 支持调用方在重启前记录
unclean 状态；持久化 `shutdown` 在生命周期进入 halted 前写入 clean execution checkpoint，失败则将
StateStore 置为 unclean 并 fail-closed。新增 runtime 分片覆盖三本的所有权、clean round-trip、unclean
recovery 和非持久 runtime 拒绝 checkpoint。该片仍不执行 AgentLoop/provider/tool/PTY，不接管 Python/L2
生产入口；下一步继续补独立 cutover/recovery 触发器与 TS bridge 只读消费边界。

该后续切片已落地：Rust `recovery::RecoveryTrigger` 对生命周期和已校验
execution checkpoint 只做 `fresh/resume_clean/recover_unclean/reject` 决策，
`KernelRuntime::recovery_decision` 不产生恢复副作用；TS `execution-checkpoint.ts`
只读消费同一三本元数据文档，校验跨表引用、排序、safe integer 与 clean/unclean
约束，并支持重新读取文件。恢复、终端/process rebind、生产 boot 和 Python/L2
fallback 仍未授权。当前 runtime 已把 `recover_unclean` 与状态/检查点
不一致的 `reject` 保留为 boot gate；调用方必须提交同代的
`acknowledge_recovery` 后才能进入 active，确认本身不执行 rebind 或
checkpoint 写入。下一步仍是独立 cutover/recovery adapter 评审。

随后补充 R4 入口预检切片：新增 `preflight::PreflightRequest` 与
`PreflightReport`，将显式 `AssemblySpec` 和宿主注入的 `StateProbe` 汇总为
确定性 assembly snapshot、state action 及 `Ready`/recovery/migration/reject
处置。`rust-kernel-preflight` 和 `make rust-kernel-preflight` 提供无 Python、
只读 JSON 自动化入口；它不探测或修改文件系统、不执行 boot、不重绑定进程、
不选择 Python fallback。该片只闭合 R4 assembly 的 entry evidence，R4 boot
ownership、真实 PTY/进程组、AgentLoop/provider/tool/DVG/R5 以及 clean cutover
仍保持高优先级未完成。

随后补齐独立 Rust entry coordinator：`entry::EntryRequest` 要求显式
assembly、JSON-safe runtime limits 和 `inspect`/`boot_once` 操作，持久化入口
只打开 Rust-owned state root；`inspect` 返回当前 recovery decision，
`boot_once` 在 `RecoverUnclean` 时必须收到同代、同 action/reason 的显式确认，
随后捕获 active snapshot 并在输出前执行 bounded clean shutdown。新增
`rust-kernel-entry` 与 `make rust-kernel-entry`，请求大小有界，错误配置和 stale/
missing recovery acknowledgement 均 fail-closed。该片闭合 R4 entry coordination
和一次性 smoke 的状态卫生，但不扫描终端、不接管 PTY/process/provider/AgentLoop，
不改变 Python 默认，也不等价于 R5 clean cutover；后续仍需真实 host adapter、
生产 reaper 和独立 cutover/recovery 评审。

随后针对会话热路径完成 Rust-native 性能切片：per-session message-id 去重与分片 registry
改用 hash index，公开 snapshot 仍在输出边界按 `session_id` 排序以保持确定性。新增
`benchmark_runner::run_session_book` 与 `rust-session-bench`，按统一 v3 schema 固定
4096 项、1/2/4 worker、3 轮测量 create/activate/input 吞吐、p95/p99、CPU/RSS 和
reject/error；该 workload 没有独立 queue，因此 queue wait 明确为 0；lock wait 仅累计
registry `try_write` 在锁不可用后的等待，不在公共 admission 快路径取时。它不与 WorkerPool 或
substrate queue contention 证据混合，也不改变 runtime authority。
2026-08-23 Linux x86_64 isolated release 基线的中位吞吐为约
1.62M/1.46M/1.37M ops/s，1/2/4 worker 的中位 write-lock wait 为
0/0.85/3.32 ms；因此读分页的并发收益不能外推到写准入，后续应以已有
batch/shard admission 候选单独优化与复测。

随后增加会话 grouped admission 候选：`SessionBook::create_batch` 先完成逐项 schema 校验，再按
shard 聚合并让每个 shard 只获取一次 registry lock；返回值保持输入顺序，重复/非法项独立失败，
不回滚同批成功项。`session.book.batch_admission` 与 `rust-session-batch-bench` 使用统一 v3
schema 单独记录 batch p95/p99，不与逐会话 admission 的延迟单位混合；该候选仍不接管 AgentLoop
或 runtime authority。
一次 release smoke 的 batch 吞吐中位数约为 1.67M/1.78M/2.64M ops/s（1/2/4 worker），
0 error/0 rejection；batch p99 中位数约为 61/133/203 us。该数字只用于同一 workload 的候选
对照，不代表默认扩缩容策略或 clean cutover 证据。

随后推进 terminal mailbox 热路径切片：`TerminalBook` 内部 registry 改用 hash lookup，
公开 snapshots 仍按 terminal identity 排序；normal mailbox I/O 通过 read-locked registry
与 per-terminal record lock 执行，`submit_input_batch`、`take_input_batch`、
`publish_output_batch`、`take_output_batch` 每批只获取一次 record lock，
保持 FIFO、sequence、capacity、drop counter 与逐帧错误语义。新增 `terminal.book.mailbox`
和 `terminal.book.batch_mailbox` 两个统一 v3 fixed-work runner 及独立 release binary，
分别记录逐帧与逐批延迟，禁止混合比较。该片仍不创建 PTY、不拥有 subprocess/AgentLoop，
后续优先级为先完成 terminal benchmark evidence，再进入 PTY/process adapter 与 AgentLoop
execution bridge 设计。当前 Linux x86_64 release smoke 的中位吞吐约为逐帧
4.47M/5.41M/3.85M ops/s、32 帧 grouped 11.2M/13.3M/7.65M ops/s（1/2/4 worker，
0 error/0 rejection）；record-lock variant 的最新中位吞吐约为逐帧
4.63M/6.00M/6.08M ops/s、32 帧 grouped 7.53M/12.14M/11.65M ops/s（1/2/4 worker），
4 worker grouped p99 中位约 5.6 us、最差轮 36.5 us。该 runner 未锁定 benchmark 主机，
跨轮/跨版本数字只作证据，不应据此授予 runtime authority。

随后推进 AgentLoop grouped admission：`Session::append_input_batch` 与
`AgentLoopHandle::admit_input_batch` 在保持 `input_seq`、message-id 去重和
partial-success 语义的前提下，分别将 session 与 loop 的锁获取压缩为每组一次；
失败项只增加 `failed_commands`，不消耗 `command_seq`。新增
`agent.loop.batch_admission` v3 runner、`rust-agent-loop-batch-bench` 入口和独立
`tests/session/kernel_test_session.rs`、`tests/session/kernel_test_agent_loop.rs`、`tests/runtime/kernel_test_benchmark_runner.rs` 覆盖。批量
p95/p99 以 batch 为单位，禁止与逐输入基线直接比较；该片仍不执行 provider/tool/PTY，
也不授予 Rust runtime authority。下一步必须在同一固定总量、同一 worker sweep 下做
release 重复采样，再决定是否保留该优化候选。
前一轮 Linux x86_64 未锁定主机的 release 对照中，batch=8/32 的 loop lock wait
曾分别约为 0.013/3.63/10.95 ms 与 0.003/3.37/7.92 ms；这些批次 p95/p99
是每批单位，不能与逐输入尾延迟直接比较。重新采用 contention-only probe 后，
逐输入吞吐中位约为 1.82M/0.76M/0.76M ops/s，batch=32 约为
1.97M/1.09M/0.95M，均为 0 error/0 rejection；对应 contended wait 中位约为
0/5.01/13.58 ms 与 0/3.34/11.48 ms。batch=32 仍未在所有 worker 点稳定胜出，
因此暂不提升为默认策略。
随后将 AgentLoop 的锁等待采样改为 contention-only：无竞争的
`try_lock` 路径不读取时钟、不执行原子累加，只有阻塞 fallback 才记录等待。
这降低了单 worker/低竞争热路径的观测开销；`lock_wait_ns` 仍只表示竞争等待，
不是锁持有时间或完整 admission 延迟。

随后完成 AgentLoop 生命周期锁优化：将跨 Session 写入的独占 loop mutex
改为生命周期 `RwLock`，并把 command/成功/失败计数改为原子累加。admission
持共享读锁，因此同一 loop 的输入可以并发进入 Session；pause/stop 仍持独占
写锁并等待在途 admission 完成，保持状态切换与 admission 的线性化边界，
`input_seq` 仍只由 Session 分配。独立 `tests/session/kernel_test_agent_loop.rs` 增加并发唯一性
向量；一次同一 v3 固定 4096 项、1/2/4 worker、3 轮的 release smoke 约为
2.49M/2.18M/0.90M ops/s，p95 约 0.23/0.59/10.65 us，0 error/0 rejection。
该结果只证明热路径候选，Session 写入竞争、PTY/进程组、ProcessTable、
GateChain/capability 和 runtime authority 仍未闭合。

随后完成受限的 Rust `ProcessPort` 一次性适配器候选：
`process_adapter::ProcessAdapter` 支持 direct argv 与由
`TerminalObservation` 派生的终端 argv 两条路径，宿主探针提供 executable
和 invocation prefix；`ProcessOptions` 传入 cwd/input/environment，分别 drain
stdout/stderr 并按流限制保留字节，超时杀死子进程并返回结构化结果。独立
`tests/process/kernel_test_process_adapter.rs`、`run_process_adapter` 与
`rust-process-adapter-bench` 已加入 Rust 测试/证据域；当前 release smoke 在
1/2/4 worker 下吞吐约 707/1404/2758 ops/s，p95 约 1.54/1.56/1.57 ms，
error/rejection 均为 0。该片只闭合值边界和受限短命命令执行，不拥有 PTY、进程组、
长生命周期句柄、reaper、ProcessTable 注册、GateChain/capability 或 AgentLoop
执行权。下一步必须先定义句柄所有权、进程组终止、取消和回收语义，再评审 adapter pilot；
因此 R3/R4/R5 仍未完成。

随后新增受限的 `managed_process::ManagedProcessBook` 生命周期候选：在 OS spawn 前预留
generation-safe `ProcessHandle`，统一管理 direct argv/terminal-derived argv child、bounded stdout/stderr drain、stdin、
observer `Pending`、显式 terminate、snapshot 与 terminal reap；独立
`tests/process/kernel_test_managed_process.rs`、`run_managed_process` 和 `rust-managed-process-bench` 已纳入 Rust 测试/证据域。
当前 release smoke 在 1/2/4 worker 下吞吐约 707/1391/2761 ops/s，p95 约 1.52/1.55/1.58 ms，
error/rejection 均为 0。容量耗尽在 spawn 前 fail-closed。PTY、进程组终止、ProcessTable 注册、
GateChain/capability、AgentLoop 与 runtime authority 仍未接入；one-shot stdin pipe 优化未显示稳定跨 worker
胜出，因此不提升为策略默认值。

随后完成 `process_bridge::ProcessTableBridge` 进程所有权候选：ProcessTable handle 是唯一对外身份，
managed child handle 仅在桥内保存。spawn 先登记 READY PCB，host spawn 成功后才转 RUNNING；spawn 失败
同时回滚 PCB，wait/terminate 将终态写为 ZOMBIE，joint reap 同时释放 managed slot 与表项。表项被外部
owner 先行回收时，桥返回结构化 `TableReap`，但无论如何释放已消费的 binding，避免不可重试的句柄泄漏；
多个 bridge 共享同一表时使用唯一 registration name。独立 `tests/process/kernel_test_process_bridge.rs` 共覆盖 10 项生命周期、
回滚、并发和共享表测试，`process.bridge.lifecycle` 使用 256 items、1/2/4 workers、3 rounds 的固定总量
基准，全部样本 0 error/0 rejection；当前未锁定 Linux x86_64 release 中位吞吐约 708/1401/2752 ops/s，
p95 约 1.55/1.57/1.63 ms。该片只闭合 R3 进程所有权候选，仍不得视为 runtime authority；PTY、进程组终止、
生产 reaper、GateChain/capability、AgentLoop execution、Rust boot 与 R4/R5 clean cutover 继续列为硬门。
同时新增 bounded `reap_finished(max_bindings)` sweep：按稳定 raw handle 选择且不超过调用方预算，只观察已经
结束的 child，不阻塞 live child，返回 inspected/reaped/pending/unavailable/errors 计数；零预算 fail-closed。
遇到外部表状态冲突仍消费 managed terminal slot，再报告错误，防止不可重试的 binding 泄漏。它是未来
caller-owned reaper 的机制接缝，不启动后台线程，也不授予生产 shutdown/reaper authority。

随后补齐 `ProcessTableBridge::stop_all_once`：按稳定 raw handle 选取有界 binding，
将调用方 timeout 传给 child termination，成功项同时释放 managed slot 与 ProcessTable
表项，并返回 terminated/reaped/pending/unavailable/errors/remaining 计数。零 budget
在触碰 child 前 fail-closed；该 API 只做一次 caller-owned pass，不启动后台 reaper，
不改变 ProcessTable 生命周期权威，后续仍需真实平台进程组信号与生产 shutdown 评审。

随后新增 `process_group::ProcessGroupBook` 与 `ProcessReaper` 候选：以 generation-safe
`ProcessHandle` 建立唯一分组归属，冻结 Active/Draining/Stopped/Failed 状态、确定性停止计划、成员终态
和有界 `max_groups/max_members` sweep。观察结果必须由 caller-owned adapter 显式提供，`Pending` 与
`Unavailable` 不改变所有权，只有匹配 stop generation 的 terminal 结果才允许回收成员。独立
`tests/process/kernel_test_process_group.rs` 覆盖容量、重复归属、leader、stale generation、终态、序列化和固定工作回收。
该片仍不发送 OS signal、不创建 PTY、不启动后台 reaper、不接管 ProcessTable/AgentLoop/Provider 或
shutdown authority；它只闭合后续 PTY/process-group adapter 所需的 Rust 机制前置边界。

随后在独立 Rust 测试域新增 `process_group_runtime::ProcessGroupRuntime` 协调候选：将
`ManagedProcessBook` 的 OS child 生命周期与 `ProcessGroupBook` 的唯一归属绑定，active 组之外拒绝
spawn，容量拒绝时先 terminate/reap 已创建 child，再返回失败；非阻塞 sweep 与显式 timeout sweep
均要求 managed slot 和 group member 双重回收后才发布 terminal outcome。`tests/process/kernel_test_process_group_runtime.rs`
覆盖固定成员预算、自然退出、取消、admission rollback 与 not-found。随后补齐
`spawn_gated_constrained`：显式 `process.spawn` capability、匹配 gate agent 与 process spec 后，
GateChain 先于 process constraint 与 spawn；GateChain 拒绝记录 gate ledger，关联不匹配在 ledger 前
fail-closed，均不创建 child。该候选仍不创建 PTY、不发送
OS process-group signal、不注册 ProcessTable、不启动后台 reaper，也不授予 AgentLoop、Provider、
shutdown 或 R4/R5 cutover 权威；下一步仍需真实 host adapter 与可观测证据。

随后完成 process-group reaper 热路径优化：`ProcessGroupBook` 以终态成员计数替代每次
`mark_terminal` 的全成员扫描，`ProcessReaper::sweep` 使用不生成 snapshot 的
`mark_terminal_and_reap` 快路径，并按本轮 `max_members` 只选择有界 handle 前缀，避免
复制未观察成员；runner 固定使用 64-member sweep budget，多轮完成全部固定工作。
独立 `process.group.reaper` fixed-work runner 与
`rust-process-group-bench` binary 按 4096 items、1/2/4 workers、3 rounds 输出统一 v3
吞吐、尾延迟和资源证据；它只测 caller-owned 机制回收，不改变 PTY、OS process-group signal、
ProcessTable、AgentLoop 或 shutdown authority 的边界。

随后补齐 process-group shutdown preparation：`ProcessGroupRuntime::drain_once`
对全部 Active group 发出一次 stop 请求，再按调用方的 `ReaperBudget` 和 timeout
执行单次 bounded sweep，报告 groups requested/already draining、reaper 计数和
remaining group/member ownership。空组在 stop 请求时直接进入 `Stopped`，不会因没有
member 而永久停在 `Draining`。该 API 不循环、不启动后台 reaper、不选默认 timeout，
重复策略与生产 shutdown authority 仍由宿主适配器持有；PTY、OS process-group signal、
AgentLoop 和 R4/R5 cutover 继续是开放硬门。

随后补齐 `ProcessGroupSignalPort` 宿主接缝：`request_stop_with_signal` 将稳定的
generation-tagged termination plan 交给平台 adapter，由 adapter 选择实际 signal/PTY
操作并返回 `ProcessGroupSignalReport`。Rust 在 reaper 前校验 group、generation 以及
bounded attempted/delivered 计数；拒绝或错报 fail-closed，组仍由 caller 持有在
`Draining`。该片不硬编码信号、不扫描终端、不启动后台 reaper；下一步仍需真实平台
adapter、权限/失败证据和生产 shutdown 评审。

随后补齐首个可注入宿主 adapter：
`host_process_group_signal::HostProcessGroupSignalPort` 在调用宿主 sender 前完整解析
所有 generation-safe handle，保持 stop plan 顺序，并拒绝零值、重复目标、解析失败及
超额 delivered；resolver/sender panic 转为 fail-closed 错误。sender 可实现
Unix/Windows 进程组、PTY 控制或测试替身；L1 不保存 signal 编号、PID 扫描、权限和 retry 策略。独立 `tests/process/kernel_test_host_process_group_signal.rs`
验证无部分派发与有界报告。这仍是候选宿主接缝，不等于真实平台 wiring 或生产 shutdown
authority 已完成。

随后补齐 ProcessTable 权威的分组执行路径：
`process_table_group_runtime::ProcessTableGroupRuntime` 将 `ProcessGroupBook`
与 `ProcessTableBridge` 组合，公开身份只保留 ProcessTable 的 generation-safe
handle；host child 与 table row 必须在终态 sweep 中共同回收，分组准入失败也
必须 joint cleanup。`bridge()` 只提供 PID/state 等有界元数据供宿主 adapter
解析，不泄漏 `Child` 或 pipe 对象。独立 `tests/process/kernel_test_process_table_group_runtime.rs`
覆盖自然退出、host signal report、容量回滚与双表收敛。这仍不授予 PTY、平台
signal 或后台 reaper 权威。

随后将 GateChain 与该 ProcessTable 权威路径合并：
`ProcessTableGroupRuntime::spawn_gated_constrained` 复用 `process.spawn` capability、
Agent identity correlation 与既有硬约束 evaluator；Gate/constraint 拒绝均在
bridge spawn 前 fail-closed，ledger 保留准入证据，授权请求继续走 ProcessTable
与 group joint reap。独立 process 测试覆盖空白名单阻断、授权执行和双表收敛。

随后将统一审计旁路接入该执行路径：`new_with_audit` 接收调用方共享的有界
`AuditLog`，记录 group create、GateChain/constraint、bridge、spawn 与 stop 的
成功/拒绝结果。审计 detail 只保留稳定的 group/handle/count/decision 元数据，
不记录 argv、环境值或宿主 PID；EventStore 持久化、保留策略与 production
shutdown 仍由宿主配置。

The Rust read-boundary slice adds `snapshot::BookSnapshotPage` to the
indexed `SessionBook`, `AgentLoopBook`, and `TerminalBook` registries.
`snapshot_page(after, limit)` keeps at most `limit + 1` record handles in a
bounded max-heap during indexed selection, sorts only that retained set, and
materializes only returned snapshots in stable identity order;
`limit` is fail-closed in `1..=512`. Its exclusive identity cursor is a live
read boundary rather than a consistent multi-page snapshot, so checkpoint and
recovery paths deliberately retain the complete deterministic `snapshots()`
contract. Independent `tests/session/snapshot_page.rs` covers cross-book ordering,
cursor continuation, bounds, and compatibility with the complete session
snapshot API. `SessionBook` registry reads now use shard-local `RwLock`s;
exclusive writes preserve admission/removal semantics, while independent
readers do not serialize behind a mutex. `rust-session-snapshot-page-bench`
uses the standard v3 4,096-request, 1/2/4-worker, three-round matrix and
measures tail latency, CPU/RSS, reject/error, plus only blocked read-lock
fallback time. The 2026-08-23 Linux x86_64 release sample reported median
17.8/18.0k versus 20.4/19.5k pages/s at one worker, 31.4/32.4k versus
35.1/37.1k at two, and 62.4/58.6k versus 63.9/70.1k at four for the
bounded-tree and max-heap selectors, respectively. Those are two alternating
three-round suites pinned to CPUs 0-3, not independent unlocked-host samples;
every paired run recorded zero rejects, errors, and read-lock wait. The
four-worker p95 varied across the suites, so the evidence supports retained
throughput improvement but not a stable tail-latency claim. There is no paired
Python-host claim and no writer-contention or runtime cutover claim.
This remains an R4 read-model/TS-bridge preparation seam only: it does not add
boot, AgentLoop execution, provider, process, or cutover authority.

为避免把读分页收益误判为写入扩展性，新增独立的
`session.book.snapshot_page_write_contention` 固定工作束：单 shard 上每项工作先校验 64 条首页，
再写入一个唯一 Session；报告沿用 v3 schema，`lock_wait_ns` 只累计被阻塞的读/写锁 fallback。
两组固定 CPU 0-3 的 release suite 均完成 4096 bundles，reject/error 为 0；1/2/4 worker 的中位
吞吐分别为 12.2/13.1k、14.1/15.4k、13.2/12.8k bundles/s，累计锁等待分别为 0ms、142-164ms、
756-772ms，p95 bundle latency 分别为 0.10-0.12ms、0.28-0.33ms、0.89-0.93ms。4 worker 的吞吐平台
与锁等待增长说明该片只建立读写竞争基线，不授予 write scaling、AgentLoop、provider、持久化或 runtime
cutover 权威；测试仍全部位于独立 Rust integration-test domain。

随后针对分页持锁时间加入 `SessionBook` shard 内部的 ordered identity index：HashMap 继续负责 duplicate
admission 与 direct lookup，`BTreeSet` 负责 identity 顺序，page 每个 shard 最多读取 `limit+1` 个 cursor
之后的 identity；create、batch、restore、closed removal 在同一 write lock 下同步维护双索引。固定 CPU 0-3
的 hash-only reference 在 `session.book.admission` 约为 1.34/1.33/1.34M ops/s，ordered index 单组样本约为
0.87/1.11/1.21M（1/2/4 worker），写入成本确实存在；但读写混合束达到约 61.7-66.4k/70.1-82.3k/
55.9-57.5k bundles/s，累计锁等待降为 0/14-19/123-127ms。该片作为明确的 read/write trade-off 记录，
仍不授予生产 scaling、AgentLoop、provider、持久化或 runtime cutover 权威。

随后将同一有序身份索引边界递进到 `AgentLoopBook` 与 `TerminalBook`：HashMap 继续负责 duplicate/direct
lookup，私有 `BTreeSet` 负责 page 的 identity 顺序；register 与 checkpoint restore 在同一 registry write
lock 下更新双索引，完整 `snapshots()` 与生命周期语义不变。新增独立的
`agent_loop.book.snapshot_page` 与 `terminal.book.snapshot_page` runner/binary，沿用 4096 records、4096
requests、1/2/4 worker、3 rounds 的 v3 量化标准；benchmark-only
`snapshot_page_with_lock_wait` 仅在 `try_read` 发现竞争后取时，公共 page API 不带计时。固定 CPU 0-3 的
一组 Linux x86_64 release 样本中，AgentLoopBook 中位吞吐约 54.2k/107.7k/207.3k pages/s，TerminalBook
约 114.6k/190.8k/297.9k pages/s；两者 reject/error/observed read-lock wait 均为 0。该样本仅是单主机机制
基线，不构成旧实现 A/B、写入竞争结论或 runtime cutover 权威；恢复索引一致性回归仍位于独立 Rust
integration-test domain。

---

### 4.6 自动化与性能外围的重写边界

当前的 `automation_exec.py`、`perf_sampling.py`、`bench_layer_runtime.py` 和
`config/discovery/automation.yaml` 属于构建/质量外围，不是 L1、L2 或 L3
的业务权威。它们不得被复制进 TS Shell 或 `l1_kernel_rs`。

外围与重写的稳定接缝固定为：

1. 执行只依赖 `ProcessPort` / `ProcessResult`；Rust 进程适配器替换后，runner
   和 manifest v1 不变。
2. 运行报告遵循版本化 JSON schema；`trace_id`、指标和证据是旁路记录，不改变
   受保护执行结果。
3. DVG 仅作为当前 L3 规划适配器；未来若依赖图下沉到 Kernel，替换
   `DependencyGraphPort` 实现，不改变 manifest 数据格式。

进入 M3 前必须完成三项解耦（G4 已在 `feature/root-kernel-preflight` 完成）：

- [x] 将 `PERF_HARNESS_*` 采样常量从 L1 `params/system.py` 迁到
  `config/quality/perf-harness.yaml`；
- [x] 为 observability/evidence/dependency graph/trace 提供稳定 L1 Port，移除
  runner 与 manifest 对 L3 具体模块的直接依赖；
- [x] 将 L2 协议基线与 M3 的固定总量 Amdahl 证据分开保存，不能用前者推导
  Rust 下沉优先级。

---

## 5. 统一里程碑

```
M0  现网基线（已完成）         — 快速核心套件全绿；契约框架已注册
M1  L2 抽象完整（部分完成）   — Phase 1–3 已接通 /api/v2/shell 三端点；剩余 Phase 4–5（Phase 6 文档同步已完成）
M2  会话收尾 + 文档            — Phase 4–5；外围契约独立（l2-shell.md 契约面已显式化）
M3  Rust-first R0/R1           — 完成语义地图、typed substrate、边界与基准 schema（前置包：`docs/design/rust-first-kernel-rewrite.md`）
M4  Rust-first R2/R3           — 固定总量性能证据与机制闭环，选择 Rust-native 调度/锁/队列/存储方案
M5  Rust-first R4/R5           — 独立入口、新状态布局、版本化协议和 clean cutover/recovery
MD  L1↔L2 线缆对接             — TS-L2 × Rust-L1 协议 v1 直连：D0 语义修复 → D1 Rust 协议主机 → D2 缝合（首片已在 feature 分支完成，默认仍 Python）
                                  （计划表与风险册：`docs/roadmaps/l1-l2-docking.md`；衔接 §5.3 割接阶梯）
```

> **M3 证据状态：已完成修正后的重复测量，但尚未闭环。** `20260818-preflight-01` 保存固定总量
> Amdahl、锁竞争和平台证据；`20260818-preflight-02` 修复 EventBus listener 生命周期，增加
> `submitted/completed/dropped/drop_rate`，并保留三轮 normal/ bounded 队列样本。normal 4/16
> listener 仍触发有界队列丢弃，bounded 曲线则在显式负载下 clean；两者不能混为一个吞吐基线。
> `20260818-preflight-03` 已复跑 Amdahl/锁竞争：`P=1.000`，RWLock 8-worker 仅约 `16k ops/s`
> 且 p95 wait `0.872ms`。RWLock 写重入深度与空 owner 已通过 Python/Rust 共享向量固定，
> 但升级/公平性/取消语义仍须审查。详见
> `docs/design/archive/002-review/2026/长期/REVIEW-2026-长期-023_kernel-readiness-preflight.md`。这些数据只决定 Rust-first
> 的基准重点和实现顺序，不代表 Python 数据格式或类布局必须保留。下一步进入 R0/R1：完成
> 语义地图、Rust-native substrate 和 benchmark schema；在 R2 证据前不授予新内核运行时权威。

---

## 6. 决策与风险

| 决策 / 风险 | 说明 |
|---|---|
| Shell 变体收敛到范式级 | 约 3 个（`terminal` / `chat` / `workspace`），不随前端数量增长 |
| 前端差异化落在渲染/绑定层 | 引擎唯一，`dispatch` 契约不变 |
| Rust-first 独立内核是既定方向 | 早期 ADR 是历史判断；新方向采用 clean-break 架构，缩放曲线决定实现顺序；**R0/R1 前置边界见 `docs/design/rust-first-kernel-rewrite.md`** |
| 共享向量的定位 | 只锁定安全/控制不变量和明确保留的 wire 字段，不承诺用户数据、Python 类布局或 Python 偶然行为兼容 |
| Python 参考实现 | 用于语义映射、回归和基准对照，不是 Rust 内部设计或性能策略的长期约束 |
| 自动化外围不进入重写核心 | manifest/报告保留为构建契约；执行、证据、指标和依赖图通过 Port 接入，不把脚手架变成 Kernel/L2 authority |
| 性能基线不等于 Rust 证据 | L2 protocol 与常规层扫描只用于回归门禁；Rust-native 方案仍须由 R2 固定总量吞吐、p95/p99、队列/锁等待和 drop JSON 决定 |
| 契约 stub 必须接通 | 否则前端无法作为纯 HTTP 客户端走通，契约框架形同虚设 |
| 会话状态迁移 | `state.py` deprecated shim 须移除，避免进程级全局态成为语言无关契约的漏洞 |

## 7. 盲区与前置门

本路线图不覆盖生产闭环、安全深化与可运维性。`docs/roadmaps/production-closure-roadmap.md`
补齐以下前置门，并作为 R4/R5 与 TS 重写的硬前置：

1. **P0 会话真值与恢复**：会话身份、`input_seq` 权威、durable JSON store、崩溃恢复、剩余执行旁路（B4/B6/B8/B9）。
2. **P0 调度/执行引擎**：超时/取消真实生效，统一执行权威落地。
3. **P1 安全与可观测性**：审计持久、VFS fail-closed、身份 keypair、备份/恢复、事件/metrics 收敛、provider 回滚。
4. **P2 治理收敛**：配置中心、schema 迁移、CoT 隐私、测试韧性、多租户隔离。

在这些前置门完成前，R0/R1/R2 的 Rust-first 工作只作**机制准备**，不得把未封口边界
复制进独立 Rust kernel 或 TS L2。

### 4.7 L1 终端能力探针与 Agent 准入门（进行中）

| Slice | 交付物 | 状态 | 后续门 |
|---|---|---|---|
| T1 | `terminal_probe`：宿主注入终端观测、能力过滤、显式优先级、argv 构造 | ✅ 候选完成 | 宿主适配器逐平台提供真实 probe observations；不能在 L1 扫描 PATH |
| T2 | `process_constraints`：Agent/Cell/ring、终端、argv、cwd、环境、资源、进程组硬约束 | ✅ 候选完成 | 将唯一执行权威接入前先补 GateChain/ProcessTable/审计联动证据 |
| T3 | `ProcessGroupRuntime::spawn_gated_constrained`：GateChain → 约束 → adapter spawn | ✅ 候选完成 | 真实 PTY/进程组信号与 reaper 仍由宿主适配器设计 |
| T3b | `HostProcessGroupSignalPort`：显式 handle→host target 解析与整批 stop sender | ✅ 候选完成 | 真实平台 signal/PTY、权限失败证据与生产 shutdown wiring 仍待完成 |
| T3c | `ProcessTableGroupRuntime`：ProcessTableBridge 与 ProcessGroupBook 统一子进程身份和 joint reap | ✅ 候选完成 | GateChain/审计统一 wiring、真实 PTY/signal 与生产 shutdown 仍待完成 |
| T3d | `ProcessTableGroupRuntime::spawn_gated_constrained`：GateChain + 约束准入接入统一身份路径 | ✅ 候选完成 | 审计旁路与真实平台执行仍待完成 |
| T3e | `ProcessTableGroupRuntime::new_with_audit`：准入/桥接/stop 共享有界审计旁路 | ✅ 候选完成 | 真实 EventStore wiring、PTY/signal 与生产 shutdown 仍待完成 |
| T4a | Rust/TS 聚合输入活动值合同、共享向量与独立测试域 | ✅ 候选完成 | 仅冻结隐私保护的聚合 reducer；不代表硬件接入或运行时权威 |
| T4b1 | `HostInputActivityPort`：宿主权限/聚合采样接缝与 fail-closed 生命周期 | ✅ 候选完成 | 真实平台采集、权限 UX、旁路监测与 production wiring 仍待完成 |
| T4b | 跨平台键盘/鼠标 adapter、权限与旁路监测联动 | 🟡 机制片已开始（`CompositeInputActivityAdapter`） | 由宿主注入 CMD/PowerShell/Bash 等平台观测；仍需真实平台 adapter、权限/隐私/失败证据，再评审生产 wiring |
| T5 | Rust 兼容入口剔除：移除隐式 shell `run`/`spawn_shell`/`PlatformDescriptor::shell_command` 与 benchmark 平台 fallback，保留 direct argv 与探针派生 argv | ✅ 本轮完成 | 对 Rust 调用方做编译迁移；benchmark 命令必须由调用方注入；不得将旧入口重新作为默认适配器 |
| T6 | 旧 Python/L2 进程执行切换前置审计与删除清单 | ⏳ 待 R4/R5 | 先完成 GateChain/ProcessTable/审计/PTY/reaper 证据，再做独立新入口切换 |

该切片只建立 L1 的终端基础和硬性准入机制，不把 CMD、PowerShell 7、Bash 或
Git Bash 的路径/开关写死，也不把 AgentLoop、provider、提示词、DVG/R5 或
生产 runtime 权威下沉。终端探测的实际系统调用属于宿主适配器；探测失败或
没有满足策略的候选时，内核选择 fail-closed。T5 只清理 Rust 候选中的
兼容入口，不等于现网 Python/L2 runtime 已完成 cutover；T6 仍以独立新入口、
恢复协议和生产执行权威闭合为前提。

T4a 已冻结输入活动的跨语言值合同：Rust/TypeScript 只接收宿主注入的来源
标签、权限、键盘/指针聚合标志和调用方时间，使用相同的 idle window、来源数
上限及 fail-closed 校验，输出既有 `InputActivitySnapshot`。共享向量和测试
分别位于 `tests/fixtures/kernel_input_activity_vectors.json`、Rust
`tests/terminal/kernel_test_input_activity.rs` 与 `systems/typescript-shell-engine/tests/shell-input-activity.test.ts`。
这一步不扫描设备节点、不保留原始键值/坐标，也不启用真实硬件监测。T4b
才负责平台 adapter、权限提示和旁路监控联动，必须另行提供跨平台隐私与失败
证据后才能进入生产 wiring 评审。

T4b1 先落地 Rust 侧 `HostInputActivityPort` 机制接缝：宿主通过
`InputActivityHostAdapter` 提供 `Granted`/`Denied`/`Unavailable` 与调用方时间的
聚合样本；Rust 复用 T4a reducer，在拒绝/不可用时返回显式 unknown，遇到非法
样本则停止适配器并 fail-closed；宿主 callback panic 也会被捕获为结构化
不可用/invalid-observation 结果。该切片不访问设备节点、不读取系统时钟、不保留
原始键值/坐标；运行期权限撤回同样停止适配器并保留 denied 快照。真实平台
采集、权限 UX、旁路监测和 production wiring 仍待宿主提供证据。

T4b 机制片进一步增加 `CompositeInputActivityAdapter`：宿主可以分别注入键盘
与指针（或其他聚合来源）adapter，由 Rust 统一串行化 start/stop/sample，
合并已授权来源的聚合快照，并在单一来源撤权时保留其他来源的可用性。来源失效
不会把原始设备数据带入 Rust；宿主仍负责平台探测、权限提示、旁路监测和
生产 wiring。所有来源失效或出现矛盾的授权结果仍 fail-closed，后续必须补
跨平台失败/隐私证据后才能推进 T4b production 评审；任何来源 callback panic
均按整体组合失败处理，不允许以部分结果冒充健康状态。

随后补齐 Python `os.py` watchdog 的纯评估边界：新增 Rust
`watchdog::WatchdogPolicy`、`WatchdogProcess` 与 `evaluate_watchdog`。单次
process pass 同时统计僵尸与 READY/RUNNING 空闲超阈值，再按 `BTreeMap`
稳定顺序生成中断突发告警；阈值边界严格使用 `>`，零阈值直接
fail-closed。该片只返回版本化 `WatchdogReport`，不读系统时钟、不启动
后台线程、不访问 ProcessTable/IRQ 单例，也不决定日志、信号、重启或
shutdown；宿主仍持有 watchdog wiring 和生产生命周期权威。独立测试位于
`tests/core/kernel_test_watchdog.rs`，下一步需把真实宿主观测、旁路审计和
生产 shutdown/restart 证据接入 R4/R5 评审，不能把这片当作 runtime
cutover 完成。

随后补齐 `os::OsCoordinator` 生命周期协调候选：通过宿主注入 boot、
persistence、shutdown hook、terminal/Cell reset 与 watchdog observer，
Rust 负责状态机、重启顺序、有界 callback 结果、状态快照以及可快速停止
的后台 watchdog loop。`get_os`/`reset_os` 仅提供适配器和测试入口，不授予
默认生产启动权；ProcessTable/IRQ 观测、日志、PTY/进程组 shutdown 与
L2/L3 wiring 仍由宿主保留。独立目标为
`tests/core/kernel_test_os.rs`，覆盖失败态、hook 顺序、timeout/panic、
restart、watchdog 与 singleton。该切片把 Python `os.py` 的机制边界映射
到 Rust，但不等于 R4/R5 cutover 或生产生命周期闭合。

随后推进 `constitution_io` 文件边界候选：Rust
`TerritoryConstitution` 已覆盖已保留的 territory/GateChain Markdown
标量、确定性渲染、版本恢复、提案合并和集合差异；`ConstitutionStore`
以单 store 锁串行化完整更新，执行 flush + 原子替换，并仅在写入成功后
发布内存快照。临时文件使用排他创建，rename 后在宿主支持时同步父目录，
避免并发写入覆盖临时文件或目录项未持久化。`kernel_test_constitution_io.rs` 以独立 policy target
覆盖 malformed known values、失败回滚、重开恢复和 8 线程磁盘/内存版本
对齐；source、GateChain key 和所选路径中的 NUL 在变更前直接 fail-closed。
该片仍是 R4 candidate：SettingsCenter/Provider 发现、提示词注入、
EventBus 联动和生产 Constitution authority 尚未接入，R5 cutover 不能据此
宣称完成。

随后补齐 Rust `transport::TransportAdapter` socket 边界候选：配置必须显式
给出 TCP/UDP 地址与边界，TCP 每连接只接收一个有界 JSONL frame，解码后的
`Message` 进入固定容量队列，并可由可选 handler 旁路消费。启动采用事务式
发布，TCP/UDP bind 或线程创建失败会回收已启动线程并清空状态；stop 在同一
生命周期锁内完成 join/队列关闭/端口清理，避免并发 restart 跨代清理。坏帧、
队列丢弃、handler panic、socket 错误和 TLS 未注入 provider 均 fail-closed
并计数，禁止 PATH/shell/主机探测。独立 `network/transport` 测试片覆盖真实
loopback 收发、UDP discovery、帧界、背压、异常隔离和重启；该片仍不接管
EventBus/card sync、protocol-host、ProcessTable、生产 boot 或 R5 authority。

随后补齐 Rust `syscall::SyscallDispatcher` 统一内核调用边界：在 handler
查找前对 operation、caller identity 和嵌套 JSON 参数执行有界校验，注册表
支持显式替换但保持确定性名称顺序；handler 错误与 panic 转换为结构化失败，
每次请求都写入注入的 `AuditLog`，并输出累计失败、panic、注册数和平均延迟
统计。`SyscallResponse::to_wire()` 保留顶层 `success/error/error_code` 语义且
防止 handler 数据伪造控制字段。独立 `tests/core/kernel_test_syscall.rs`
覆盖注册上限、未知/非法请求、并发计账与异常隔离。具体 process/event/resource
操作仍须宿主显式注册并经过 capability policy；该片闭合统一机制入口，但不
授予 Rust production runtime authority，后续要与 `KernelRuntime`、GateChain
和 L2/TS bridge 做明确 adapter 接线。

本轮继续完成了 syscall 读路径和第一组显式接线：handler 查找改为
`RwLock` 读共享，注册仍走写锁；热路径使用共享 `Arc<str>` 名称的 hash
索引，确定性快照另保留有序索引，避免每次 dispatch 的树查找。`register_batch`
在发布前一次性校验名称、重复项和容量，容量不足时不留下部分注册。`KernelSyscallAdapters` 以一次原子
批注册提供 `kernel.runtime.snapshot`、`kernel.runtime.recovery` 与
`kernel.capability.status` 三个只读操作，参数非空即 `EINVAL`，非持久化恢复
读取以 `EIO` fail-closed。参数 JSON 大小校验改为有界 writer 计数，超过上限
立即失败而不保留完整临时缓冲。该片通过独立
`tests/runtime/kernel_test_syscall_adapters.rs`，仍不接入 process/event/
allocator 的副作用操作、不绕过 GateChain，也不授予生产入口权威；后续再按同一
模式接入经过 capability policy 的具体宿主适配器。

随后完成 Rust `skill::SkillRegistry` 机制切片：以 Rust-native typed metadata
承载 SkillManager 的 L1 机制面，覆盖写授权、builtin 只读、生命周期、
productive/offensive posture、progressive disclosure、agent/Cell/global
scope、Cell 绑定、usage/useful/dimension 计数、确定性查询与目录视图、
staged guidance、card-completion advancement、dependency/next DAG 检查、
虚拟 `/skills` listing，以及版本化内存 checkpoint/restore。内容边界、
NUL/身份校验和未知引用均在变更前 fail-closed；独立
`tests/policy/kernel_test_skill.rs` 与 `tests/fixtures/kernel_skill_vectors.json`
锁定该机制切片。Markdown/YAML 发现、Prompt/EventBus/R4 provider、
Card/TODO/AgentLoop 策略、L2/API 路由、Python 状态导入和 production
authority 明确留在宿主，后续 TS/L2 只消费版本化值合同，不引入兼容替换。

随后补齐 Rust `settings` 机制切片：`SettingsRegistry` 重建 Python
`l1.kernel.settings` 的默认值目录、fallback 读写、分类查询、
批量更新、reset/reset_all，以及 `prompt.inject.*` 的 fail-safe 读取。
宿主可注入经过完整快照校验的 `SettingsProvider`；provider 自己持有
持久化与授权，provider 失败不会静默退回旧值。设置 key 和总量均有
Rust-native 上限，fallback 批量更新先 staged 再一次提交，避免半应用。
独立 `tests/storage/kernel_test_settings.rs` 覆盖默认面、provider 转发、
非法身份、快照拒绝与 prompt safety。该片补齐 L1 settings 语义机制，
但不读取 Python 状态、不替代 `ConfigStore`、不热加载服务、不决定
engineering-debug policy，也不授予 R4/R5 runtime authority；下一步优先
将 settings facade 作为 Rust-owned runtime/TS 只读桥的显式 adapter 接线。

---

**规划结束。** 下一步为 M1 剩余项与 R0/R1 并行：完成 Phase 4–5（会话收尾 + 底层边界留位标注；
Phase 6 文档同步已完成），并建立 Rust-native substrate 与固定总量 benchmark schema。Rust 与 TS 在 R4/R5
完成前都不得成为默认路径；新内核不读取旧 Python 用户数据，也不以 Python 兼容替换为目标。
