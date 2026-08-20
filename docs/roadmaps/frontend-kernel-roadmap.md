# Praxis 前端与内核多语言路线图

> 状态：G4 自动化外围已闭合；G5 Rust/TS 迁移脚手架已启动；Rust-first 独立内核重写仍按 R0–R5 与 M1–M4 门槛推进
> 关联决策：`docs/decisions/praxis-tech-stack-decision.md`（内核纯 Python）、`docs/decisions/praxis-mvp-decision.md`
> 关联设计：`docs/design/praxis-load-adaptive-pool-design.md`、`docs/architecture/l5-user.md`、`docs/architecture/l2-shell.md`

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

仍待完成：Phase 4（会话收尾，移除 `state.py` deprecated shim）、Phase 5（底层边界文档标注转化位）、
Phase 6（`l2-shell.md` 契约面同步——当前仍写 `execute_tool_spec`，与 `invoke_capability` 实码不符）。

| Phase | 动作 | 落点 |
|---|---|---|
| **1. 接通命令执行** | `_shell_dispatch` stub → `l2.l2_shell.dispatch(text, session)` | `src/l4/api_handlers/api_handlers_agent.py` |
| **2. 接通补全** | `_shell_autocomplete` stub → `l2.l2_shell.completer.autocomplete()` | 同上 |
| **3. 接通命令列表** | `_shell_commands` stub → `l1.kernel.commands.get_registry().list()` | 同上 |
| **4. 会话收尾** | `ShellSession` 全接管，移除 `state.py` deprecated shim | `src/l2/l2_shell/state.py` |
| **5. 底层边界留位** | 确认 process/fs/terminal 走 `ProcessPort`/`FilesystemPort`/`WorkerPort` + L4 通道；仅文档标注转化位 | `l2-shell.md` "Bottom-layer boundary" 表格（fs/worker 已接 port，`ProcessPort` 为 Rust 下沉候选） |
| **6. 文档同步** | 更新 `docs/architecture/l2-shell.md` 契约面 | l2-shell.md |

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
已被后续设计演进覆盖**：`docs/design/praxis-load-adaptive-pool-design.md`（2026-08）已为
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
5. 新内核以独立入口和新状态目录启动；Python、DVG、R5/Mer、AgentLoop 和提示词策略不进入
   Rust kernel，前端通过明确版本的协议桥接。

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
`src/l1/kernel/` 的每个 Python 文件机械搬运。保持不变的是经过 R0 确认的安全/控制不变量和
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
（prompts、skills、model/provider、cards、DVG、R5/Mer、AgentLoop）移入 Rust。

这一定义允许最终完成机制层的 Rust 实现，同时避免把 Python 的偶然行为或用户数据格式带入新内核。

当前分支的增量证据：Rust `worker` 候选已完成一个隔离切片（bounded
queue、FIFO 淘汰、结果句柄、panic 结构化失败、优雅 drain、idle shrink），
并通过 38 项 Rust 测试、fmt/clippy 和 Python WorkerPort 回归。它仍未接入
`WorkerPort`、boot 或任何运行时执行权威；取消、task timeout、adaptive
sampling 与 Python 异常映射仍是 G6 前置决策。

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

随后完成 `registry_base` 声明式注册基座候选：Rust 镜像 descriptor 默认值、重复
拒绝与显式覆盖、注册顺序、分类过滤、公开序列化和 register/unregister 统计；共享
`kernel_registry_base_vectors.json` 在 Python/Rust 两侧通过，Rust workspace 测试总数
达到 127 项。handler 闭包、领域 registry、发现/boot 注册和 runtime routing 仍由
Python/适配器持有；该候选不接入 Port、boot 或生产执行权威，也不解除 G3/G6。

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
状态快照和缺失 owner 解锁错误，Python/Rust 独立测试域均通过。排队 writer 公平性、取消、跨进程
所有权和运行时锁路由仍是开放项；EventBus 异步丢弃与公平性继续单独评审，不由该 fixture 推断。

随后补齐 EventBus 确定性 parity：共享 `kernel_event_vectors.json` 固定有界 history、按类型过滤、
signal 序列化和无 listener 时的 dispatch 计数，Python/Rust 独立测试域均通过。callback 调度、过载
丢弃、shutdown 公平性和 SSE/WS fan-out 仍不由该向量判定。

随后补齐 `process` 生命周期 parity：共享 `kernel_process_vectors.json` 固定 PID/PCB 注册、
READY/RUNNING 往返、identity verified、取消后的 STOPPED 终态、exit→ZOMBIE→reap、tokens/cards/scouts/CPU
记账与去时间戳后的 audit 顺序，Python/Rust 独立测试域均通过。Python zombie reaper、interrupt 触发、
allocator/limiter 清理、长生命周期 OS handle 和运行时路由仍是适配器副作用，不纳入 Rust 候选契约。

R1 已启动：Rust `substrate` 提供 generation-tagged process handle、确定性 shard plan 与无 JSON
分配的 atomic queue metrics，`benchmark` 提供固定总量报告 schema；它们只冻结所有权/观测基元，
不接管 ProcessTable、调度、boot 或运行时路由。`state_queue` 已提供分片 slot map、代际校验、
终态转换和 fail-fast 有界队列；`benchmark_runner` 已提供固定总量 contention smoke，覆盖
worker/round 完整性、p95/p99、队列/admission 等待和拒绝计数，吞吐由固定完成量与墙钟时间推导。
`reputation` 已提供显式策略注入的 G5 分数 ledger，但 singleton、持久化、provider 和 GateChain
路由仍在适配器侧；`notify` 已提供显式时间戳、有界保留、最新优先查询和 drop 计数的旁路
buffer，但 EventBus/SSE/WS/webhook 投递仍在适配器侧。`BenchmarkEvidence` 已提供带 schema、平台、架构、
runtime、revision 和 runner 归属的完整 JSON 导出，`make rust-benchmark` 可重复生成 queue contention
证据；这仍不是完整 R2 基线，CPU、内存、Python 参考测量与 workload-specific drop 分析待补。进入
R2/R3 前仍不授予新内核运行时权威。`identity_binding` Rust candidate 已收敛 `(cell, role)` 元数据、
fail-closed 写门、Cell 容量、UID rebind 稳定性、revision 与确定性 snapshot；prompt/definition、持久化、
事件和 API/L2Shell 仍由适配器持有，不能作为 Python registry 的兼容迁移。
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
随后新增 `assembly` R4 seam：`KernelAssembly` 组合 `BootPlan`、`StateLayoutManifest`、`PortRegistry` 与 halted
lifecycle，独立 `rust-kernel` binary 可在无 Python/FFI 下输出确定性 JSON snapshot；共享
`kernel_assembly_vectors.json` 在 Rust/Python 两侧通过。当前仍不读配置、不创建 state root、不执行 callback、不实例化
provider；fresh-root 创建、versioned protocol serving 与 durable recovery 是下一组 R4 施工项，也不解除 G3/G6。

---

### 4.6 自动化与性能外围的重写边界

当前的 `automation_runner.py`、`perf_harness.py`、`perf_quality.py` 和
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
M1  L2 抽象完整（部分完成）   — Phase 1–3 已接通 /api/v2/shell 三端点；剩余 Phase 4–6（会话收尾 + 文档同步）
M2  会话收尾 + 文档            — Phase 4–6；l2-shell.md 契约面显式化；外围契约独立
M3  Rust-first R0/R1           — 完成语义地图、typed substrate、边界与基准 schema（前置包：`docs/design/rust-first-kernel-rewrite.md`）
M4  Rust-first R2/R3           — 固定总量性能证据与机制闭环，选择 Rust-native 调度/锁/队列/存储方案
M5  Rust-first R4/R5           — 独立入口、新状态布局、版本化协议和 clean cutover/recovery
```

> **M3 证据状态：已完成修正后的重复测量，但尚未闭环。** `20260818-preflight-01` 保存固定总量
> Amdahl、锁竞争和平台证据；`20260818-preflight-02` 修复 EventBus listener 生命周期，增加
> `submitted/completed/dropped/drop_rate`，并保留三轮 normal/ bounded 队列样本。normal 4/16
> listener 仍触发有界队列丢弃，bounded 曲线则在显式负载下 clean；两者不能混为一个吞吐基线。
> `20260818-preflight-03` 已复跑 Amdahl/锁竞争：`P=1.000`，RWLock 8-worker 仅约 `16k ops/s`
> 且 p95 wait `0.872ms`。RWLock 写重入深度与空 owner 已通过 Python/Rust 共享向量固定，
> 但升级/公平性/取消语义仍须审查。详见
> `docs/design/reviews/2026-08-18-kernel-readiness-preflight.md`。这些数据只决定 Rust-first
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

---

**规划结束。** 下一步为 M1 剩余项与 R0/R1 并行：完成 Phase 4–6（会话收尾 + `l2-shell.md`
契约面同步），并建立 Rust-native substrate 与固定总量 benchmark schema。Rust 与 TS 在 R4/R5
完成前都不得成为默认路径；新内核不读取旧 Python 用户数据，也不以 Python 兼容替换为目标。
