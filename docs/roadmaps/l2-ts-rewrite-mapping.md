---
pointer: ROADMAP-2026-08-23-011
archive_number: ROADMAP-2026-长期-011
fonds: ROADMAP
year: 2026
retention: 长期
title: "L2 TS 重写映射清单（2026-08-23）"
author: L3
formation_date: 2026-08-23
carrier: md
classification: 内部
pages: 179
archivist: L3
reviewer: L3
archive_date: 2026-08-29
source: roadmap
keywords: []
abstract: "- Python L2：`systems/python-reference-runtime/l2/` 22 文件 / 3550 行（commands / selector / i18n /"
series: active
date: 2026-08-23
status: active
construction: in_progress
---

# L2 TS 重写映射清单（2026-08-23）

> 状态：feature/l2-ts-rewrite 分支工作参考。本文档按 **main 当前实际代码**
> 建立映射（非 handoff 旧假设），供 TS 重写逐模块对齐。

## 0. 现状基线（main）

- Python L2：`systems/python-reference-runtime/l2/` 22 文件 / 3550 行（commands / selector / i18n /
  shell_completer / shells/* / l2_shell/* / protocol/*）。
- TS 已落地（分支）：`systems/typescript-shell-engine/src/` —— 协议镜像
  `wire-envelope.ts`/`wire-records.ts` + `engine/`（parser / dispatcher / bridge /
  session / builtins）+ `engine/transports/`（stdio / http / ws / ssh）。
- ⚠️ **bridge.py 不存在于 main**：handoff §1.2 声称的 `systems/python-reference-runtime/l2/bridge.py`
  （92 函数 / 49 allowlist）已不在仓库；L2 当前直接 import L3/L4
  （`l3.error_bus`、`l3.params`、`l4.ports`、`l4.adapters.i18n_yaml`）。
  TS 侧 `engine/bridge.ts` 已是协议 v1 客户端形态——**正确方向**：TS
  一律经协议转发，不复制 Python3 的进程内桥。

## 1. 映射总表

| Python3 模块 | 关键符号 | TS 对应 | 状态 |
|---|---|---|---|
| `protocol/envelope.py` | `Outbox`/`SessionCursor`/`make_message`/`validate_message` | `systems/typescript-shell-engine/src/wire-envelope.ts` | ✅ 已有（镜像，非破坏性 ack） |
| `protocol/records.py` | `SessionIdentity` | `systems/typescript-shell-engine/src/wire-records.ts` | ✅ 已有 |
| `protocol/host.py` | `ProtocolHost.handle`/`_emit`/`_advance_shared_cursor` | `engine/bridge.ts`（客户端）+ `interactive-session.ts`（SessionView） | 🟡 部分：客户端/投影已有；host 权威留 Python3 |
| `l2_shell/__init__.py` | `dispatch(text)` / `_l3a_intent` / `_lookup_alias` | `engine/parser.ts` + `engine/dispatcher.ts` + `engine/route.ts` | ✅ 路由、alias、本地/bridge/L3A 分流已映射；权威执行留 host |
| `shells/base.py` | `Shell(ABC)` / `run` | `engine/terminal-shell.ts`（方言适配器合同） | ✅ `classify`/`run`/session 工厂已落地；renderer 输出合同已落地 |
| `shells/family.py` | `ShellFamily.register/bind/resolve` | `engine/session-family.ts` | ✅ 已实现（注册、绑定、配置、revision、snapshot） |
| `shells/session.py` | `ShellSession`（direct/l3a 切换） | `engine/routing-session.ts` | ✅ 已实现（路由态快照；无 L3/L1 句柄） |
| `shells/terminal.py` | `TerminalShell.run/loop` / `intent_direct` / `scout_commission` | `engine/terminal-shell.ts` + `engine/terminal-view.ts` + `engine/terminal-renderer.ts` | 🟡 方言运行、history、`$`/`/`/pipeline/tool/L3A` 与无 I/O 行记录渲染已映射；REPL 输入循环与真实前端接入仍留前端 |
| `commands.py` | `CommandRegistry`（system/user 分离、YAML 加载、revision） | `engine/dispatcher.ts`（注册表 + listCommands） + `engine/command-catalog.ts`（YAML 元数据 + alias 索引，Phase A） | 🟡 部分：注册/查询 + 元数据面已有；handler 注册与 system/user 分离留 host |
| `selector.py` | `select`/`preconnect`/`_scan_injection` | `engine/agent-selector.ts`（选择投影 + preconnectImpact/riskLevelOf，Phase A） | ✅ 投影面已映射（扫描与 LLM reviewer 权威留 Python3） |
| `shells/family.py` | `ShellFamily`（register/bind/resolve/loadConfig/revision/snapshot） | `engine/session-family.ts`（前端→方言解析，首注册为默认） | ✅ 已实现 |
| `shells/session.py` + host 状态容器 | `ShellSession` / `_advance_shared_cursor` | `engine/session-manager.ts`（一会话 N 视图游标 + 共享水位=落后视图） | ✅ 已实现 |
| `i18n.py` | `t()`/`set_locale`/`register_file` | locale 数据 + `lang` builtin + 终端/选择器展示键（Phase A） | ✅ 已实现（`systems/typescript-shell-engine/src/locale-catalog.ts`） |
| `shell_completer.py` + `l2_shell/completer.py` | `TerminalCompleter.complete`/`get_command_names`/`get_aliases` | 本地补全（桥数据渲染候选） | ✅ 已实现（`engine/command-completion.ts`） |
| `l2_shell/commands_settings.py` | 配置写面 | 经桥 `settings_set`（单一写权威） | ✅ 已实现（`engine/command-groups.ts`） |
| `l2_shell/output_guard.py` | 输出守卫 | 展示安全镜像（权威留 Python3） | ✅ 已实现（`engine/output-policy.ts`） |
| `l2_shell/state.py` | `ShellState` 访问器 | `SessionView` 快照 | 🟡 部分 |

## 2. 实现批次（按依赖）

1. **第一批（2026-08-23 ✅）**：`bridge.ts` 命令域分组（与 Python3 命令语义 1:1，
   dict 返回优先）+ `i18n` locale 数据接入（`lang` builtin 返回真实
   locale 列表）+ 协议层 parser 结构化 args（免 shlex）。
2. **第二批（2026-08-23 ✅）**：selector 投影（cell/agent 选择结果渲染）+ completer
   （命令名/别名/工具名候选）+ 命令组注册（对齐 commands_settings 域）。
3. **第三批（2026-08-23 ✅）**：ShellFamily/方言解析（`engine/route.ts`：
   `!`/`$`/`/` 路由到 dispatcher + 桥转发，管道 + L3A 回退）+ output_guard
   镜像（`engine/output-policy.ts`）+ ssh transport readiness handshake
   （连接前写入排队、attach 后 flush）。

> 三批已全部完成并合入分支（Vitest 49 passed，e2e stdio 真实 Python3
> host 不回归）。剩余可选：ShellFamily 前端绑定映射（interactive-session.ts
> 已覆盖 SessionView）、移动端真实 SSH 端点（远端 stdio host 已通，按需接入）。

## 2a. 第四批（2026-08-28，feature/l2-ts-phase-a ✅）

本地元数据/展示投影补全，全部为纯投影（不拥有 authority）：

1. **命令目录（`engine/command-catalog.ts`）**：解析共享 `config/commands.yaml`
   YAML 子集（标量/flow 列表/flow 对象/块列表项/注释剥离），alias 反查索引 +
   revision 计数（镜像 `commands.py` 元数据面）。`commands.py` 映射状态由
   🟡 部分 → ✅ 元数据面已映射（system/user 分离与 handler 注册仍留 host）。
2. **终端视图（`engine/terminal-view.ts`）**：help/tools/intent/scout/system/tool
   六类结果形状投影（镜像 `shells/terminal.py` 返回形状）；`locale-catalog.ts`
   补 en 展示键（terminal.*/selector.*，Python locales 尚未同步，渲染回退键名）。
   `shells/terminal.py` 映射状态由 ⏳ → 🟡（REPL 循环与渲染仍留 Python/前端）。
3. **注入扫描投影（`agent-selector.ts` preconnectImpact/riskLevelOf）**：
   风险分级对齐参考阈值 0.3/0.7（`params/agent.py`），host 判定仍权威。
   `selector.py` 映射状态由 ⏳ → ✅ 投影面已映射（`_scan_injection`/LLM reviewer
   权威仍留 Python，符合铁律 §3）。
4. **集成面**：`builtins.ts` 全量 `/help`（catalog）；`route.ts` catalog alias
   本地解析前置（桥回退不变）；`command-completion.ts` catalog 候选并入。

> 验收：`tsc --noEmit` + Vitest 284 passed / 8 skipped（+30 新用例），
> system-naming PASS。下一梯队：G5 切默认（Rust 前置）与 terminal REPL 终态。

## 2b. Rust terminal-backed AgentLoop 投影（2026-08-30）

`engine/rust-agent-loop-terminal.ts` 是受限的 TS/L2 read model，对应 Rust
`agent_loop_terminal::AgentLoopTerminalBridge` 的保留值合同。它验证
loop/session/terminal 三元绑定、生命周期状态、safe sequence、1 MiB 单帧
和 256 帧批上限，接受 JSON `number[]` 及本地 `Uint8Array`，并在输出前
复制字节。未绑定、稀疏数组、非法字节/流向、未知状态、超长身份和绑定
漂移均 fail-closed。

该模块不拥有 AgentLoop、session、terminal、mailbox 或持久化权威，不执行
decoder/provider/tool，不创建 PTY、不选 shell、不决定 dequeue/retry。它只
为未来 L2/前端渲染或转发提供可验证的值投影；TS 专测 4 个用例，Rust
对应专测 5 个用例。G5/G6 的 host 切换条件和终端 REPL 终态不因该投影提前
满足。

## 2c. 第五批（2026-08-30，TS terminal dialect/session ✅）

本批把 Python3 `Shell`/`ShellSession`/`TerminalShell.run` 的**输入边界**
迁移为独立 TS 方言适配器，同时保留 Python3/Rust host 的执行权：

1. `engine/routing-session.ts`：对齐 `L3A`/`DIRECT` 路由态、`cell_id` /
   `agent_id` / `session_id` 快照；只保存字符串值，不持有 Cell、AgentLoop、
   terminal、outbox 或 capability。
2. `engine/terminal-shell.ts`：复用 `parseRoute`、`Dispatcher`、`ProtocolBridge`
   实现空输入、`help`/`tools`/`status`/`history`、`$` system、pipeline、
   `/` engine、Direct tool 和 L3A intent；history 使用有界
   `CommandHistory`，结果返回解码后的协议消息。
3. `engine/route.ts`：补上 Python3 兼容的模式分流——默认 L3A 将裸文本
   发为 `l3a_send`，只有显式 Direct session 才将裸文本发为 tool；不改变
   `$`/`/`/pipeline 的顺序或 host authority。

> 验收：新增 `routing-session.test.ts` 与 `terminal-shell.test.ts` 共 9
> 例；连同 `conformance.test.ts` 路由回归切片 25/25 通过，TS `typecheck`
> 通过。仍未满足 terminal REPL 终态、真实前端接入、G5 默认 Rust host
> 切换或 G6 移除 Python host。

## 2d. 第六批（2026-08-30，REPL-neutral terminal renderer ✅）

本批把 Python3 `TerminalShell._render_banner` / `_render` 的展示语义提取为
独立 TS 行记录合同，供 REPL、TUI、IDE、HTTP 或 SSH 前端消费：

1. `engine/terminal-renderer.ts`：将 `TerminalRunResult`、`result`、
   `stream_chunk`、`event` 响应投影为 `{ role, text }` 行记录；覆盖
   banner、help、tools、intent、scout、system、tool、history、generic
   success/error，结果键排序与字段/输出上限保持有界。
2. renderer 只做纯格式化：不写 stdout、不读 stdin、不创建 PTY、不执行
   OS/工具、不持有 L3/L1 对象句柄；`I18n` 可注入，默认使用 TS `en`
   字典，前端可自行决定颜色、布局和传输。
3. `tests/terminal-renderer.test.ts` 新增 7 个切片用例；与
   `terminal-view` / `terminal-shell` 回归切片合计 25/25，通过 TS
   `typecheck`。真实 REPL 输入循环、五前端接入、G5 Rust 默认切换和 G6
   Python host 移除仍未完成。

## 3. 铁律（与 handoff §2.3 一致）

1. TS 不拥有最终 authority：outbox/ack/会话状态在 Python3 host。
2. TS 绝不重实现 AgentLoop / Tool Pipeline / Workflow / Scheduler /
   Memory / Planning——一律经 bridge 转发。
3. 本地 handler 只做纯解析/展示/格式转换。

## 4. 验收

- 每批：`tsc --noEmit` + `vitest run` 全绿 + 端到端（spawn 真实
  Python3 ProtocolHost）不回归。
- 镜像同步：协议改动 Python3/TS 双端同步（handoff §2.4）。


## 5. Authority 割接标准（2026-08-23 定向）

> **方向确认（操作员 2026-08-23）**：Python3 仅作抽象快速迭代基座，**TS L2 是终态权威**，
> 承载上层会话接入面并对接 Rust L1 内核。本节定义真相源从 Python3 `ProtocolHost`
> 迁移到 TS 引擎的验收标准；未全部满足前维持双端共存（铁律 §3）。

### 5.1 权威迁移范围

| 真相源 | 现权威（Python3） | 目标权威（TS） |
|---|---|---|
| Outbox 追加/淘汰 | `protocol/host.py _emit` | `engine/outbox`（wire-envelope.ts 已镜像） |
| Ack 游标推进 | `_advance_shared_cursor` | `session-manager.ts`（共享水位=落后视图） |
| 会话注册表 | `_get_session` 惰性创建 | `session-manager.ts` 会话生命周期 |
| Envelope 校验 | `validate_message` | `validateMessage`（golden vectors 锁定） |

### 5.2 割接前置门槛（全部满足才可切换）

1. **覆盖证据**：authority 四模块（envelope / session-manager / bridge / records）
   stmts ≥ 95% 且 branch ≥ 90%（当前 94.4% / 91.1%，envelope 97.9% 已达标）。
2. **行为等价**：协议 v1 全 KIND golden vectors 双端跑同结果——Python3 输出作为
   参考向量冻结，TS 必须逐字节复现 canonical JSON 排序。
3. **E2E 反转测试**：现有 e2e.stdio（TS 客户端 → Python3 host）通过后，补
   反转形态——Python3 客户端 → TS host，同一测试矩阵全绿。
4. **持久化兼容**：会话游标/outbox 快照文件可被双端互读（round-trip 不丢字段）。
5. **回滚路径**：割接后保留 Python3 host 一个版本周期，配置开关可切回。

### 5.3 割接执行序

```
G1 覆盖达标 → G2 向量冻结 → G3 反转 e2e 绿 → G4 持久化互读 → G5 切默认 + 开关 → G6 移除 Python3 host（一个版本后）
```

每步独立提交、独立证据；任一步失败回退上一步状态。

> **执行序实例化（2026-08-28，feature/l2-g-cutover）**：
>
> | 阶梯 | 状态 | 证据 |
> |---|---|---|
> | G1 覆盖达标 | ✅ 已达成 | authority 四模块 stmts/branch：envelope 98.97/98.18、bridge 97.36/90.69、records 95.93/90.54、session-manager 99.06/93.02（门槛 95/90） |
> | G2 向量冻结 | ✅ 已达成 | `protocol_v1_conformance.json` canonical_envelopes 补全 7 KIND（ack/command/control/event/intent/result/stream_chunk）；TS/Python3 逐字节一致（three-way-vectors + test_conformance_vectors 44 passed）；Rust gate 待二进制构建后纳入（见 §5.4 线缆契约） |
> | G3 反转 e2e 绿 | ✅ Rust host 变体已达成 | `e2e.rust.stdio` 4 例启用并扩展（command 往返 / attach-recovery / 未注册命令 fail-closed / 多视图非破坏性 ack）；`PRAXIS_RUST_HOST_BIN` 指向 `rust-protocol-host`（D2 后 G3 的 Rust 变体按 l1-l2-docking §3 定义满足） |
> | G4 持久化互读 | ✅ 已达成 | `session-store.e2e.test.ts` 双向 round-trip（Rust probe emit→TS 读、TS 写→Rust validate）+ `store_version:99` fail-closed；共享 fixture 双端消费 |
> | G5 切默认+开关 | ⏳ L2 侧接口已冻结（§5.4），Rust 前置未就绪 | Rust host 接入 boot/Port 生产路径（Rust 侧 Agent）；验收清单见 §5.4 |
> | G6 移除 Python3 host | ⏳ G5 后一个版本 | 见 §5.4 |

> **实例化（2026-08-23）**：TS-L2 × Rust-L1 线缆对接的阶段计划、里程碑表与风险册见
> `docs/roadmaps/l1-l2-docking.md`（D0 语义修复 → D1 Rust 协议主机 → D2 缝合）。
> 其 M-D2 完成即满足本阶梯 G3 的 Rust host 变体；M-D2 后由 G1–G6 接管割接。

### 5.4 G5 切默认：L2 侧接口对齐规格（2026-08-28，供 Rust 侧 Agent 执行）

> 本阶梯 R3 教训：Rust 侧由另一 Agent（GPT-5.6Terra）推进，L2 侧只锁定
> **接口契约与开关语义**，不在本阶梯做 Rust 实现；Rust host 接入 boot/Port
> 属 Rust 侧前置。以下为 L2 侧冻结的对接面，Rust 侧改动必须逐条满足。

**开关语义（TS 侧已实现，`src/engine/transports/rust-host.ts`）**：

| 项 | 语义 |
|---|---|
| `PRAXIS_RUST_HOST` | 显式取值 `1/true/yes/on/rust` 才启用 Rust；默认及未知值回 Python（`isRustHostEnabled`/`resolveHostImplementation`） |
| `PRAXIS_RUST_HOST_BIN` | 指定 host 可执行文件路径；未设置时回退命令名 `rust-protocol-host`（PATH 解析，`defaultRustHostBinary`） |
| `PRAXIS_PYTHON` / `PRAXIS_PYTHON_HOST_CWD` | Python 回滚路径的显式解释器与 cwd（`createConfiguredHostTransport`） |
| child 生命周期 | 出错/退出即时拒绝 pending 请求（`recordProcessError`）；`close()` 幂等；stderr 独立捕获 |

**Rust host 必须满足的线缆契约（三端一致，改动须同步向量）**：

1. 行协议：stdin 一行一 envelope，stdout 一行一响应，canonical JSON 键序（sortKeys）；
   Python3/TS/Rust 同输入必须逐字节一致（共享 `protocol_v1_conformance.json`）。
2. 帧上限：1 MiB UTF-8 字节上限三端固定；超限请求在 TS 适配层先拒绝（不写入 host）。
3. 错误通道：host 侧错误走 stderr，不污染 stdout JSONL 流。
4. KIND 路由：command（L1 面直答、未注册 fail-closed denial + trailing ack）、
   control（attach/ack/recovery，per-view cursor + 共享水位=最落后视图，非破坏性 ack）、
   intent 经透传管道转 L3 权威面（本计划范围外，只透传）。
5. 执行门：`$` 系统命令强制携带 ring/danger 元数据并经 capability 门裁决，审计含拒绝路径。

**G5 前置（Rust 侧，GPT-5.6Terra 执行）**：rust-protocol-host 接入 boot/Port 生产路径，
从 candidate-only 变为可配置默认候选；三方向量持续同步（R4：任何一侧改动必须同步向量）。

**G5 切默认验收（L2 侧动作，Rust 前置就绪后）**：

- [ ] 默认 host 从 Python 切 Rust，`PRAXIS_RUST_HOST=0/off` 等可回切 Python（显式开关）
- [ ] e2e 矩阵全绿：`e2e.stdio`（TS→Python）+ `e2e.rust.stdio`（TS→Rust）+ 反转方向
- [ ] 三方向量（TS/Python/Rust）逐字节一致无回归
- [ ] 保留 Python host 一个版本周期 → G6 移除

**G6 移除 Python3 host（G5 后一个版本）**：移除 `python -m l2.protocol`/`ProtocolHost`；
验收：全链路无 Python host 引用，TS↔Rust 直连为唯一生产路径。
