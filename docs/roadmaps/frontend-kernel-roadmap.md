# Praxis 前端与内核多语言路线图

> 状态：规划阶段（未动工）
> 关联决策：`docs/decisions/praxis-tech-stack-decision.md`（内核纯 Python）、`docs/decisions/praxis-mvp-decision.md`
> 关联设计：`docs/design/praxis-load-adaptive-pool-design.md`、`docs/architecture/l5-user.md`、`docs/architecture/l2-shell.md`

---

## 0. 概述

Praxis 的后续前端将覆盖四种形态：**TUI**、轻量化桌端 App（开箱即食的 ChatBox）、
重量化桌端 App（VSCode 级的人机共生开发平台）、远程协作 Web 端。本路线图回答两个问题：

1. **前端多样化如何影响 L2 Shell 变体规模？** —— 结论：Shell 变体收敛到"交互范式"级（约 3 个），
   不随前端数量增长；前端差异全部落在渲染/绑定层，不触及 L2 引擎。
2. **Rust 重写底层 L1 何时做、先优化哪个热路径？** —— 结论：Rust 下沉内核是**既定方向**；
   Amdahl 缩放曲线决定**迁移顺序与时机**（先优化高串行占比热路径），经 port 适配器无侵入替换。

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

现状：**语言无关契约的框架已就绪，但实现是 stub**。L4 路由已注册（`api_routes.py`），
但 `api_handlers_agent.py` 的三个 handler 是空壳：

```
POST /api/v2/shell                  → _shell_dispatch    → {"success": False, "error": "shell dispatch not available"}   ← stub
GET  /api/v2/shell/autocomplete     → _shell_autocomplete → {"success": True, "suggestions": []}                          ← stub
GET  /api/v2/shell/commands         → _shell_commands    → {"success": True, "commands": []}                              ← stub
```

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
Rust 迁移铺路，明确 `l1_kernel_rs` 复用同一套常量与决策公式、Python 侧先灰度、Rust 落地后
接口不变整体替换。因此 **Rust 重写底层 L1 是路线图的既定方向**，不是被排除的选项。

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

### 4.3 无侵入下沉路径

1. 候选热路径先以纯数值算法/纯函数隔离（如 `load_adaptive.py` 控制律，无 I/O、可单测）。
2. Rust 侧 `l1_kernel_rs` 复用同一套常量与决策公式，`params/` 与 `praxis.yaml` 为唯一真源。
3. Python 侧先灰度（如 `LOAD_ADAPTIVE_ENABLED`），Rust 落地后整体替换，**port 接口不变**。
4. 换语言只改适配器，不改内核调用方（`cross-cutting.md` 端口抽象）。
5. 范围以 L1 内核系统调用面为界（process/fs/terminal/sandbox 等 port 适配器），与前端
   TS Shell 走语言无关契约形成闭环——前端 TS、内核 Rust、中间语言无关契约。

### 4.4 演进模型澄清（选择性下沉 vs 整体重写）

**演进模型不是"Python 临时占位 → 稳定后整体重写 Rust"。** 而是：

```
Python 内核（长期首选实现）
   │  port 抽象（FilesystemPort/WorkerPort/...）
   ▼
Rust 热路径下沉 —— 当缩放曲线证明某模块为串行瓶颈（P 高）时
   │  经 port 适配器替换该模块，接口不变，Python 灰度共存
   ▼
l1_kernel_rs（模块级，非整体重写）
```

- **Python 是长期的、首选实现**，不是临时代码占位；ADR 的"不值得引入"是成本判断，不是"先用 Python 顶着"。
- **Rust 是选择性、模块级、无侵入下沉**：一次只替换一个被缩放曲线证明为瓶颈的热路径模块（如
  `ThreadPoolWorker`），经 port 适配器替换，接口不变，Python 灰度共存。
- **抽象稳定 ≠ 预定整体重写**：port 抽象稳定解决"能不能换"（可选、无侵入），缩放曲线解决
  "该不该换"（顺序与时机）。二者结合，做到"需要时无痛替换，不需要时保持 Python"。
- **前端 TS、内核 Python/Rust、中间语言无关契约三者解耦**：任一端多语言化都不影响另一端。

---

## 5. 统一里程碑

```
M0  现网基线（当前）           — 快速核心套件全绿；契约框架已注册（stub）
M1  L2 抽象完整               — Phase 1–3 接通 /api/v2/shell 三端点；TS/TUI 可作纯 HTTP 客户端
M2  会话收尾 + 文档            — Phase 4–6；l2-shell.md 契约面显式化
M3  Rust 下沉优先级判定       — 完成真实固定总量 L1 基准；据 P 值和锁/队列等待定"先迁移哪个热路径"
M4  Rust 热路径下沉           — 经 port 适配器无侵入替换，Python 灰度共存，接口不变
```

> **M3 证据状态：未在仓库中固化任何特定平台结果。** 过去的 `sleep`/SHA 与每 worker 全量工作曲线
> 不代表固定总量的 L1 热路径，因此撤回其 Rust 优先级结论。每次决定迁移顺序前，均须按 §4.2 在目标平台
> 完成真实基准并保存 JSON，再根据 P 值、吞吐、队列等待和锁等待决定首个 Rust 下沉模块；在此之前，Python
> 保持首选实现。

---

## 6. 决策与风险

| 决策 / 风险 | 说明 |
|---|---|
| Shell 变体收敛到范式级 | 约 3 个（`terminal` / `chat` / `workspace`），不随前端数量增长 |
| 前端差异化落在渲染/绑定层 | 引擎唯一，`dispatch` 契约不变 |
| Rust 下沉内核是既定方向 | 早期 ADR 判断已被 load-adaptive 设计覆盖；缩放曲线只决定顺序/时机；**前置边界封口见 `kernel-boundary-audit.md` §11.2（Phase 0/1 先于任何迁移）** |
| Rust 迁移无侵入 | 经 port 适配器替换，`l1_kernel_rs` 复用同一套常量，Python 灰度共存，接口不变 |
| 契约 stub 必须接通 | 否则前端无法作为纯 HTTP 客户端走通，契约框架形同虚设 |
| 会话状态迁移 | `state.py` deprecated shim 须移除，避免进程级全局态成为语言无关契约的漏洞 |

---

**规划结束。** 下一步为 M1：接通 `/api/v2/shell` 三端点（纯 Python，符合现有架构）；Rust 下沉内核为后续既定方向，按缩放曲线确定迁移顺序。
