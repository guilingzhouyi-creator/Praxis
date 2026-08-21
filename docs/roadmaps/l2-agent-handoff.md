# L2 Shell — 后续 Agent 交接索引与 TS 重写标准

> 供后续 Agent 审阅/接手 L2 层工作时的**精确索引参考与重写标准**。
> 与 `docs/roadmaps/l2-multifrontend-session-layer.md`（进程状态）配套：本文档是**操作性手册**（在哪、怎么改、验收什么），路线图是状态记录。
> 分支：`feature/l2-cleanup`（未合入 main，工作区干净，HEAD 见 `git log`）。

## 0. 阅读指南（给后续 Agent）

1. 先看本文档 §1 能力地图 → 找到要动的模块 → 读对应源码（**禁止未读先改**）。
2. 涉及跨语言契约改动（envelope/records/kind）→ 必读 §2.4 镜像同步要求。
3. 涉及 P3 TS 引擎 → 必读 §2 全部（重写标准）。
4. 提交前：`make precommit`（ruff + size + attribution）+ commit-scan（scope 注册表，见 §3.4）。
5. 测试：Python 走 WSL venv（§3.2 命令），TS 走 WSL nvm node（§3.1）。

## 1. L2 能力地图（模块 → 文件 → 关键符号 → 状态）

状态图例：✅ 完成 · 🟡 骨架/部分 · ⏳ 未开始

### 1.1 协议 v1（统一会话契约）— ✅ 完成

| 模块 | 关键符号 | 状态 |
|---|---|---|
| `src/l2/protocol/envelope.py` | `KINDS`（七类）、`make_message`、`validate_message`、`encode/decode_message`、`Outbox`（非破坏性 ack + `unacked(after_seq)`）、`SessionCursor`（`ack(seq)`） | ✅ |
| `src/l2/protocol/host.py` | `ProtocolHost.handle`（line 入口——TS `roundTrip` 对端）+ `handle_message`（dict 直入——stdio/ws/web 共享，validate-once）、`_handle_validated`、`_advance_shared_cursor`（per-session 索引 + 共享水位=落后视图）、`attach_view`/`view_cursor`/`session_state`、`_emit` | ✅ |
| `src/l2/protocol/records.py` | `SessionIdentity`（terminal/process 可空） | ✅ |
| `src/l2/protocol/schema.py` | `ENVELOPE_JSON_SCHEMA`（契约钉） | ✅ |
| `src/l2/protocol/projection.py` | `register_projection`/`project`/`available_frontends`（web/TUI/desktop + 未知回退） | ✅ |
| 契约钉测试 | `tests/l2/test_protocol_v1.py`、`tests/l2/test_protocol_records.py`、`tests/l2/test_projection.py`、`tests/l4/test_shell_protocol.py` | ✅ 53 passed |

联动语义（**改动前必读**）：命令/意图 → `_emit` 写共享 outbox → 每视图按 `cursor.last_acked` 重放；`KIND_ACK`/control `resume/recovery` 均按 `view_id` 推进游标并 `_advance_shared_cursor`；**一视图 ack 永不抹除他视图重放窗口**。

### 1.2 L3 command bridge — ✅ 完成（92 函数 / 49 条 allowlist）

| 项 | 位置 |
|---|---|
| 桥模块（L2→L3 唯一边界） | `src/l2/bridge.py`（按域：memory/system/model/selector/injection/card/plugin/cell/terminal） |
| allowlist | `tests/infra/test_layer_imports.py` 中 `("l2/bridge.py", ...)` 条目（**业务文件零 L3 直连**） |
| 已迁文件（allowlist 清零） | memory、system、model、commands_settings、ci、departments、extra_*、connect、common、selector、completer、l3ac、l3a、harness、terminal、`__init__` 等 26 个 |

**TS 对应**：桥函数按协议命令语义命名、dict 返回优先（`think_registry_stats`↔`/intents`、`cell_liveness`↔cell 查询）；对象句柄零泄漏（cell 用 `cell_ids`/`cell_liveness`/`cell_agent_reachable`/`cell_territory`）。

### 1.3 注入策略（安全）— ✅ 完成

| 项 | 位置 |
|---|---|
| L3 守卫 | `src/l3/services/injection_guard.py`（模式表/阈值裁决/`set_llm_reviewer`/`reset_injection_guard`） |
| 桥函数 | `l2.bridge.injection_verify`/`injection_scan`/`set_llm_reviewer` |
| 消费方 | `src/l2/selector.py` `preconnect`（注入段单次 `injection_verify` 调用） |
| 测试 | `tests/l2/test_selector.py`（经桥 `injection_scan`） |

### 1.4 配置写面 — ✅ 完成（P1 收尾）

- 唯一权威写面：L3 `settings_center`（经桥 `settings_set(key, value)`）。
- L1 `kernel.settings` 只作默认值只读面；ACB 槽位写属绑定域保留。
- 收敛点：`/config`、`/settings global`、`/ci set`、`/ci toggle`。

### 1.5 TS 引擎（P3）— ✅ 完成（引擎 + 四 transport + WS 对接已合入 main）

| 模块（`packages/protocol-ts/src/engine/`） | 状态 |
|---|---|
| `parser.ts` | ✅ 引号分词 `parseLine`/`tokenize` |
| `dispatcher.ts` | ✅ 注册表 + `listCommands` + 未注册回退桥标记 |
| `bridge.ts` | ✅ `ProtocolBridge`（command/attach/ack/replay，transport 注入） |
| `session.ts` | ✅ `SessionView`（attach/replay/投影）+ `projectWeb/Tui/Desktop`（与 Python `projection.py` 三形状对齐） |
| `builtins.ts` | ✅ `registerBuiltins`（lang/help/clear 本地纯展示命令） |
| transport 适配器 | ✅ `transports/`——**共享引擎** `line-transport.ts`（ack 边界 + 超时/行上限 + 并发拒绝）+ stdio（Node readline）/ http（fetch `/api/v2/shell`）/ ws（原生 WebSocket，实例可注入）/ ssh（ssh2 channel，客户端可注入）；**异步契约** `(line) => Promise<string[]>` |
| 端到端 | ✅ `tests/e2e.stdio.test.ts`——spawn 真实 Python `ProtocolHost`（`python -m l2.protocol`）打通：command 往返 + attach/replay |
| 测试 | ✅ engine 8 + protocol 6 + session 7 + e2e 2 + transports 6（Vitest 29 passed，tsc 干净） |

协议镜像：`packages/protocol-ts/src/{envelope,records}.ts`（与 Python 逐字段对齐，§2.4）。

### 1.6 Shell 命令域 — ✅ 完成

- `src/l2/l2_shell/commands/*.py`（66 个 handler，签名 `(args, session=None)`）。
- i18n：47 处 f-string 全收编 `shell.app_error.*`（31 key × 4 locale），`test_i18n_l2_regression` 正则含 f-string 盲区。
- `/history` 真实现（在途 Agent 提交 `6cb40f5`）：`src/l2/shells/session.py` + `l2_shell/__init__.py`。

### 1.7 L2 层 TS 重写映射总表（后续 Agent 快速定位）

| L2 模块 | 关键符号 | TS 对应 |
|---|---|---|
| `src/l2/protocol/`（envelope/host/records/projection） | `Outbox`/`SessionCursor`/`ProtocolHost`/`SessionIdentity` | `packages/protocol-ts/src/{envelope,records}.ts` + `engine/bridge.ts` |
| `src/l2/bridge.py`（92 函数） | 域分组：error bus / memory / system / model / selector / injection / settings | `engine/bridge.ts`（1:1 转发，域分组同构） |
| `src/l2/commands.py` | `CommandRegistry`（系统/用户命令分离） | `engine/dispatcher.ts`（register / has / listCommands / 未注册回退桥标记） |
| `src/l2/selector.py` | dict 数据 API（cell_ids / cell_liveness / ...） | 本地投影（渲染选择结果，零对象句柄） |
| `src/l2/i18n.py` | `t()` / `set_locale()` / `get_locale()` | locale 数据 + `lang` builtin |
| `src/l2/shell_completer.py` / `l2_shell/completer.py` | Tab 补全 | 本地纯展示（桥数据渲染候选） |
| `src/l2/shells/`（base / family / session / terminal） | 方言/家族/会话/终端 | `engine/session.ts`（SessionView 投影形状 + 前端矩阵） |
| `src/l2/l2_shell/__main__.py` | REPL 路由（/命令、\| 管道、纯文本→L3A） | `engine/parser.ts` + `dispatcher.ts` 路由模型 |
| `src/l2/l2_shell/commands/*.py` | 20+ 命令模块（memory / connect / extra...） | dispatcher 注册组（未注册回退桥标记） |
| `src/l2/l2_shell/commands_settings.py` | 配置写面 | 经桥 `settings_set`（单一写权威） |
| `src/l2/l2_shell/output_guard.py` | 输出守卫 | 展示安全镜像（权威留 Python） |
| `src/l2/l2_shell/state.py` | 状态访问器 | `SessionView` 快照（attach/replay） |

### 1.8 协议会话边界（L2 作为上层会话统一协议承载面）

- **协议会话**（L2）：`ProtocolHost._get_session(session_id)` 惰性创建的 `ShellSession`（shell="protocol"）——session_id 级、独立于任何 Agent 运行；承载上层前端（web/TUI/desktop/SSH）的**统一会话**（视图游标 + 共享 outbox + 三形状投影）。
- **≠ AgentLoop 会话**（L3A session system——L3 层，Agent 内部对话/思维链/工具失败记录）：协议 v1 **不承载 AgentLoop 会话级语义**——它只是上层前端到 L2 引擎的统一接入面。
- **≠ 全系统会话**：不承载内核/服务生命周期会话。
- **内部接入**：L2 REPL（`python -m l2.l2_shell`）直连 `dispatch()`（交互式本地优化，全局默认 state）；**外部前端一律经协议 v1**（envelope → ProtocolHost）——统一协议承载面覆盖外部，内部 REPL 为直连例外（如需协议承载可经 host 的 REPL 会话改造）。

### 1.9 协议优化全景与 TS 架构预留（2026-08-21）

**性能优化（Python 侧，已合入 main）**：

| 优化 | 文件 | TS 重写对应 |
|---|---|---|
| `run()` 批量 flush（stdio I/O） | `host.py` | TS 无等价——直接批量写（天然继承） |
| `_advance_shared_cursor` per-session 索引 | `host.py` | `session.ts` 视图索引同构（attach 即入索引） |
| ws 桥 dict 直入（省 JSON 往返） | `host.py`/`ws_bridge.py` | TS 天然无 JSON 往返（对象直传） |
| command args 直入（省 shlex.split） | `host.py`/`l2_shell/__init__.py` | TS 天然无 shlex——命令名/参数已结构化 |
| `_get_session` 会话类缓存 | `host.py` | TS 类导入零成本（无需该模式） |
| 常量化（OUTBOX_MAXLEN→params）+ 配置驱动（WS 端口） | `params/api.py`/`l4/params.py` | TS 常量/配置来自 Python 真相源（镜像注释） |

**TS 架构预留（模块划分预案——重写直接采用）**：

| Python 职责（host） | TS 模块 | 说明 |
|---|---|---|
| `handle(line)`（JSONL 行解析 + 路由） | `protocol.ts` 行解析 + `bridge.ts` 路由 | 行协议解析独立模块 |
| `handle_message(dict)`（envelope 校验 + 分发） | `envelope.ts`（validate）+ `bridge.ts`（dispatch） | 校验与分发分离 |
| `_handle_validated`（KIND 分支） | `dispatcher.ts`（kind 路由） | command/control/intent/event 分支同构 |
| `_handle_control`（会话流） | `session.ts`（attach/replay/ack/detach） | 会话流步骤注释见 §1.7 |
| `_emit`（envelope 构造 + outbox 追加） | `envelope.ts`（Outbox——非破坏性 ack） | outbox 窗口 1024 来自 params |
| `_get_session`/`_get_outbox`/`_cursors` | `session.ts` 状态容器 | per-session 状态单一容器 |

架构预留要点：
- **单一协议入口**：TS 只经 `bridge.ts`（零运行时状态）——一切命令经协议 v1 envelope 转发 Python 宿主。
- **权威留 Python**：TS 永不重实现 AgentLoop / Tool Pipeline / Workflow / Scheduler / Memory / Planning。
- **契约单一真相**：envelope / records / params 的 TS 镜像注释均指向 Python 源文件。
- **架构基线**：`docs/architecture/l2-shell-engine.md`（引擎层）+ `l2-shell.md`（家族层）为本文档的稳定契约；本表与 §1.7/§1.8 为路线图视角。

## 2. TS 重写标准（P3 翻译规范）

### 2.1 跨语言契约（协议 v1 是唯一契约）

- envelope 字段：`v / session_id / seq / ts / trace_id? / kind / payload`；七类 kind：`ack / command / control / event / intent / result / stream_chunk`。
- 校验语义：command 需非空 `name` + 字符串数组 `args`；control 的 `op ∈ attach/detach/resume/recovery/ack`；ack 需非负 `ack_seq`。
- **Python 侧为参考实现**（`src/l2/protocol/envelope.py`），TS 侧为镜像（`packages/protocol-ts/src/envelope.ts`）——任何契约改动两边同步（§2.4）。

### 2.2 桥 API 对应表（Python bridge ↔ TS bridge.ts）

| 语义 | Python（`src/l2/bridge.py`） | TS（`src/engine/bridge.ts`） |
|---|---|---|
| 发命令 | `settings_set` 等 92 函数（直接调用） | `bridge.command(name, args)` → 协议消息给 Python 宿主 |
| 附视图 | `attach_view(view_id, session_id)` | `bridge.attach(sessionId, viewId?)` |
| 确认 | `cursor.ack(seq)` + `_advance_shared_cursor` | `bridge.ack(ackSeq, viewId?)` |
| 重放 | `outbox.unacked(after_seq)` | `bridge.replay(sessionId, viewId?, lastAcked)` |

**原则**：Python 桥是进程内直接调用；TS 桥是协议客户端（经 transport 发消息）。两者是**同一概念边界的两种传输**，不是逐行移植。

### 2.3 铁律（TS 侧红线）

1. TS **不拥有最终 authority**：outbox/ack/会话状态在 Python ProtocolHost。
2. TS **绝不重实现** AgentLoop / Tool Pipeline / Workflow / Scheduler / Memory / Planning——一律经 bridge.ts 转发。
3. 本地 handler（dispatcher + builtins）只做纯解析/展示/格式转换。

### 2.4 镜像同步要求（改动协议必做）

1. Python `envelope.py` 改动 → 同步 `packages/protocol-ts/src/envelope.ts`（逐字段/逐语义）。
2. 同步补测试：Python `tests/l2/test_protocol_v1.py` 与 TS `tests/protocol.test.ts` 断言**行为等价**（例：非破坏性 ack 跨视图）。
3. 验收：`tsc --noEmit` + `vitest run` + Python 契约钉全绿。

### 2.5 P3 验收清单

- [x] `session.ts`：视图投影（身份 + unacked 事件 → 前端形状），`projectWeb/Tui/Desktop` 与 Python `projection.py` 三形状一致（含未知前端回退 web）。
- [x] `builtins.ts`：`lang`/`help`/`clear` 纯展示命令本地实现（`registerBuiltins` + `dispatcher.listCommands`）。
- [x] transport 适配器：**异步 Transport 契约**（`(line) => Promise<string[]>`）+ 共享 `line-transport.ts` 引擎；`stdio.ts`（Node readline）/ `http.ts`（fetch 双模式）/ `ws.ts`（原生 WebSocket）/ `ssh.ts`（ssh2 channel）**四适配器全落地**（fake/mock 测试覆盖，`tests/transports.test.ts` 6 例）。
- [x] 端到端真实链路：TS 引擎 + 真实 Python ProtocolHost 打通（`tests/e2e.stdio.test.ts` spawn `python -m l2.protocol`；command 往返 + attach/replay）。
- [x] 测试：Vitest 全绿（29 passed）+ Python 联动测试（`tests/l4/test_shell_protocol.py` 等 53 passed）不回归。
- [x] L3 零改动：TS 引擎增量仅 `packages/protocol-ts/`（Python 零触碰）。

### 2.6 Transport 适配器标准（后续 Agent 扩展 WS/SSH 时遵循）

1. **接口**：实现 `Transport = (line: string) => Promise<string[]>`（发一行 JSONL envelope，resolve 响应行）。
2. **位置**：`packages/protocol-ts/src/engine/transports/<name>.ts`，并在 `index.ts` 导出。
3. **响应边界**：每请求返回该请求的响应行（stdio 按 ack 行；HTTP 按 `envelopes` 数组）；**禁止跨请求混合**（并发请求应拒绝或排队）。
4. **健壮性**：超时（`timeoutMs`）+ 行数上限（`maxLines`），失败快返回错误（host 卡死不挂死调用方）。
5. **测试**：真实适配器配 fake/本地宿主测试；端到端配真实 Python host（参考 `tests/e2e.stdio.test.ts`）。

## 3. 已知坑与运行环境（必读）

### 3.1 TS 工具链（WSL 无 node）

- node 在 `~/.nvm/versions/node/v24.19.0/bin`；用**显式最小 PATH**（`export PATH=...:/usr/bin:/bin`）——Windows 中文括号路径（`（x86）`）会炸 bash 引号。
- 验证：`cd packages/protocol-ts && ./node_modules/.bin/tsc --noEmit && ./node_modules/.bin/vitest run`（先 `npm ci` 一次）。

### 3.2 Python 测试（WSL 内）

- 主树 venv：`/home/guiling/dev/praxis/.venv/bin/python`（worktree 无 `.venv`）。
- 必须 `-o addopts=""` 串行（默认 `-n auto` 在 WSL 极慢）。
- 例：`wsl -d Ubuntu -- bash -c 'cd /home/guiling/dev/praxis-l2-cleanup && /home/guiling/dev/praxis/.venv/bin/python -m pytest tests/l2/ -o addopts="" -q'`。

### 3.3 Git（worktree 怪癖）

- WSL 侧 git 解析不了 worktree 的 `.git` 引用（exit 128）——**提交/查看走 Git Bash 侧**（bash 工具默认 shell）。
- 新建 worktree 后先 `git config --global --add safe.directory '%(prefix)///wsl.localhost/Ubuntu/home/guiling/dev/praxis-<name>'`。

### 3.4 提交门禁

- commit-scan：`type(scope):` 的 scope **必须在 `config/discovery/commits.yaml` 注册**（`l2`/`shell`/`i18n` 已注册；`ts` 未注册——用 `l2`）。
- pre-commit：ruff → ruff format → size → attribution；无会话证据时用 `PRAXIS_AUTHOR=AtomCode PRAXIS_MODEL=deepseek-v4-flash`。
- 提交 message 必须含 Co-Authored-By trailer（`Co-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>`）。

## 4. 下一步清单（按依赖顺序）

1. **P3 收尾**：真实 SSH 端点接入（远端 stdio host 已通，按需）+ 五前端矩阵真实接入。
2. **协议 host 优化**（`feature/python-perf` 分支进行中）：per-session 水位索引、ws 桥 dict 直入（合入时同步本文件 §1 状态列）。
3. **P4 重型/移动**：VSCode 共生平台（投影 + diff 流 + 多路会话）、移动 SSH 适配器。
4. **合入/推送**：双绿后 `MERGE_GATE_SKIP` 决策由用户授权；`make push-both` 双推前确认网络。

---

*索引随分支演进更新；改动本文件时同步刷新 §1 状态列与 §2 验收清单。*
