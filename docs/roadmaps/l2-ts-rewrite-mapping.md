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
| `l2_shell/__init__.py` | `dispatch(text)` / `_l3a_intent` / `_lookup_alias` | `engine/parser.ts` + `engine/dispatcher.ts` | 🟡 部分：解析/分派已有；alias 反查、`_l3a_intent` 路由未映射 |
| `shells/base.py` | `Shell(ABC)` / `run` | `engine/interactive-session.ts`（SessionView） | 🟡 部分：会话视图已有；Shell 方言抽象未映射 |
| `shells/family.py` | `ShellFamily.register/bind/resolve` | `engine/interactive-session.ts`（前端绑定） | ⏳ 需重写（前端→方言解析） |
| `shells/session.py` | `ShellSession`（direct/l3a 切换） | `engine/interactive-session.ts`（SessionView 快照） | 🟡 部分 |
| `shells/terminal.py` | `TerminalShell.run/loop` / `intent_direct` / `scout_commission` | `engine/builtins.ts` + 桥转发 | ⏳ 需重写（方言语法 `!`/`$`/`/` 分派） |
| `commands.py` | `CommandRegistry`（system/user 分离、YAML 加载、revision） | `engine/dispatcher.ts`（注册表 + listCommands） | 🟡 部分：注册/查询已有；load_defaults/系统用户分离未映射 |
| `selector.py` | `select`/`preconnect`/`_scan_injection` | 本地投影（dict 数据 API，零句柄） | ⏳ 需重写（选择结果渲染，权威留 Python3） |
| `shells/family.py` | `ShellFamily`（register/bind/resolve/loadConfig/revision/snapshot） | `engine/session-family.ts`（前端→方言解析，首注册为默认） | ✅ 已实现 |
| `shells/session.py` + host 状态容器 | `ShellSession` / `_advance_shared_cursor` | `engine/session-manager.ts`（一会话 N 视图游标 + 共享水位=落后视图） | ✅ 已实现 |
| `i18n.py` | `t()`/`set_locale`/`register_file` | locale 数据 + `lang` builtin | ✅ 已实现（`systems/typescript-shell-engine/src/locale-catalog.ts`） |
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

> **实例化（2026-08-23）**：TS-L2 × Rust-L1 线缆对接的阶段计划、里程碑表与风险册见
> `docs/roadmaps/l1-l2-docking.md`（D0 语义修复 → D1 Rust 协议主机 → D2 缝合）。
> 其 M-D2 完成即满足本阶梯 G3 的 Rust host 变体；M-D2 后由 G1–G6 接管割接。
