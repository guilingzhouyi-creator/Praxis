# L2 TS 重写映射清单（2026-08-23）

> 状态：feature/l2-ts-rewrite 分支工作参考。本文档按 **main 当前实际代码**
> 建立映射（非 handoff 旧假设），供 TS 重写逐模块对齐。

## 0. 现状基线（main）

- Python L2：`src/l2/` 22 文件 / 3550 行（commands / selector / i18n /
  shell_completer / shells/* / l2_shell/* / protocol/*）。
- TS 已落地（分支）：`packages/protocol-ts/src/` —— 协议镜像
  `envelope.ts`/`records.ts` + `engine/`（parser / dispatcher / bridge /
  session / builtins）+ `engine/transports/`（stdio / http / ws / ssh）。
- ⚠️ **bridge.py 不存在于 main**：handoff §1.2 声称的 `src/l2/bridge.py`
  （92 函数 / 49 allowlist）已不在仓库；L2 当前直接 import L3/L4
  （`l3.error_bus`、`l3.params`、`l4.ports`、`l4.adapters.i18n_yaml`）。
  TS 侧 `engine/bridge.ts` 已是协议 v1 客户端形态——**正确方向**：TS
  一律经协议转发，不复制 Python3 的进程内桥。

## 1. 映射总表

| Python3 模块 | 关键符号 | TS 对应 | 状态 |
|---|---|---|---|
| `protocol/envelope.py` | `Outbox`/`SessionCursor`/`make_message`/`validate_message` | `src/envelope.ts` | ✅ 已有（镜像，非破坏性 ack） |
| `protocol/records.py` | `SessionIdentity` | `src/records.ts` | ✅ 已有 |
| `protocol/host.py` | `ProtocolHost.handle`/`_emit`/`_advance_shared_cursor` | `engine/bridge.ts`（客户端）+ `session.ts`（SessionView） | 🟡 部分：客户端/投影已有；host 权威留 Python3 |
| `l2_shell/__init__.py` | `dispatch(text)` / `_l3a_intent` / `_lookup_alias` | `engine/parser.ts` + `engine/dispatcher.ts` | 🟡 部分：解析/分派已有；alias 反查、`_l3a_intent` 路由未映射 |
| `shells/base.py` | `Shell(ABC)` / `run` | `engine/session.ts`（SessionView） | 🟡 部分：会话视图已有；Shell 方言抽象未映射 |
| `shells/family.py` | `ShellFamily.register/bind/resolve` | `engine/session.ts`（前端绑定） | ⏳ 需重写（前端→方言解析） |
| `shells/session.py` | `ShellSession`（direct/l3a 切换） | `engine/session.ts`（SessionView 快照） | 🟡 部分 |
| `shells/terminal.py` | `TerminalShell.run/loop` / `intent_direct` / `scout_commission` | `engine/builtins.ts` + 桥转发 | ⏳ 需重写（方言语法 `!`/`$`/`/` 分派） |
| `commands.py` | `CommandRegistry`（system/user 分离、YAML 加载、revision） | `engine/dispatcher.ts`（注册表 + listCommands） | 🟡 部分：注册/查询已有；load_defaults/系统用户分离未映射 |
| `selector.py` | `select`/`preconnect`/`_scan_injection` | 本地投影（dict 数据 API，零句柄） | ⏳ 需重写（选择结果渲染，权威留 Python3） |
| `i18n.py` | `t()`/`set_locale`/`register_file` | locale 数据 + `lang` builtin | 🟡 部分：lang builtin 已有；locale 数据未接入 |
| `shell_completer.py` + `l2_shell/completer.py` | `TerminalCompleter.complete`/`get_command_names`/`get_aliases` | 本地补全（桥数据渲染候选） | ⏳ 需重写 |
| `l2_shell/commands_settings.py` | 配置写面 | 经桥 `settings_set`（单一写权威） | ⏳ 需重写（命令注册组） |
| `l2_shell/output_guard.py` | 输出守卫 | 展示安全镜像（权威留 Python3） | ⏳ 需重写 |
| `l2_shell/state.py` | `ShellState` 访问器 | `SessionView` 快照 | 🟡 部分 |

## 2. 实现批次（按依赖）

1. **第一批（本轮）**：`bridge.ts` 命令域分组（与 Python3 命令语义 1:1，
   dict 返回优先）+ `i18n` locale 数据接入（`lang` builtin 返回真实
   locale 列表）+ 协议层 parser 结构化 args（免 shlex）。
2. **第二批**：selector 投影（cell/agent 选择结果渲染）+ completer
   （命令名/别名/工具名候选）+ 命令组注册（对齐 commands_settings 域）。
3. **第三批**：ShellFamily/方言解析（`!`/`$`/`/` 路由到 dispatcher +
   桥转发）+ output_guard 镜像。

## 3. 铁律（与 handoff §2.3 一致）

1. TS 不拥有最终 authority：outbox/ack/会话状态在 Python3 host。
2. TS 绝不重实现 AgentLoop / Tool Pipeline / Workflow / Scheduler /
   Memory / Planning——一律经 bridge 转发。
3. 本地 handler 只做纯解析/展示/格式转换。

## 4. 验收

- 每批：`tsc --noEmit` + `vitest run` 全绿 + 端到端（spawn 真实
  Python3 ProtocolHost）不回归。
- 镜像同步：协议改动 Python3/TS 双端同步（handoff §2.4）。
