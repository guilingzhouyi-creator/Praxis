# Rust-Readiness Hardening Plan — Python 侧封口（先于 Rust 重写）

> 状态：Phase 0 已实施（`feature/kernel-boundary-hardening`，未合并）；Phase 1/2 未动工
> 依据：`docs/roadmaps/kernel-boundary-audit.md`（评分 42/100，§5 绕过路径 / §11 落地顺序）
> 关联：`docs/roadmaps/frontend-kernel-roadmap.md`（M3/M4 Rust 下沉）、`docs/roadmaps/multilang-migration.md`（`l1_kernel_rs` 槽位）
> 范围：仅 Python 侧改造，**不写任何 Rust 代码**；目标是把 `l1_kernel_rs` 将来要替换的契约收敛到最小、机制化、不可绕过。

---

## 0. 目标与非目标

**目标**：在不切换语言的前提下，把当前 Kernel 变成"机制唯一、执行单门、授权 fail-closed、审计持久、进程状态真实"的边界，使 Rust 下沉时只需替换机制模块（sync/event/process/allocator/gatechain/constitution），策略与业务全部留在 Python/config。

**非目标**：不引入 Rust 代码；不改 UI/CLI 行为；不改变业务语义（除安全默认值外）；不做一次性大爆炸重构（每个工作流独立可合入、可回滚）。

---

## 1. WS1 — 单一执行门（Execution Gate，最高优先）

> 目标：消灭审计 §5 的 B1/B2/B3——任何工具执行路径都必须经过同一授权链。

| 子项 | 改动 | 文件 |
|---|---|---|
| W1.1 | `execute_tool_spec` 改名 `_execute_tool_spec`（私有）+ pipeline 作用域守卫 `require_pipeline_scope()`（基于调用栈/显式 token） | `src/l3/tool_system/tool_spec.py` |
| W1.2 | 新增 `src/l3/tool_system/invoke.py::invoke_gated(tool_name, args, agent_id, ...)`——唯一公开的受门工具调用入口，内部包 ToolPipeline；L2/MCP/API 全部改用它 | `invoke.py`（新）、`src/l2/shells/terminal.py:248`、`src/l4/api_handlers/api_handlers_mcp.py:413` |
| W1.3 | `ToolSpec` 增加 `gated: bool`；`LLMEngine._execute_one_tool` 对未 `gated` 的 spec 直接报错（拒绝裸 handler 执行） | `src/l4/llm/llm_tools.py:22`、`src/l3/tool_system/tool_spec.py`、`src/l3/agent/agent_loop.py:367`（`_wrap_handler` 置位） |
| W1.4 | 新增 AST 静态测试 `tests/infra/test_single_execution_gate.py`：禁止 `execute_tool_spec(`/`.handler(` 出现在白名单（tool_pipeline_steps / agent_loop._wrap_handler / invoke.py / run_code 后端）之外 | `tests/infra/test_single_execution_gate.py`（新） |
| W1.5 | `/api/v2/cards/sideload` 删除或改走卡片管线（审计 B5） | `src/l4/api/api_handlers_cards.py`、`src/l4/api/api_routes.py` |

**验收**：全仓库无一处工具调用不经 `invoke_gated`/pipeline；静态测试拦截新增绕过；RING_3 工具（execute_shell 等）在 L2/MCP 路径同样触发 witness approval。

## 2. WS2 — Fail-closed 授权与鉴权

| 子项 | 改动 | 文件 |
|---|---|---|
| W2.1 | `_auth_ok` 增加配置 `api.auth.deny_when_unconfigured`（默认 **True**）：无静态 token 且无 AuthPort → 401；显式配置 `false` 才维持旧开放行为 | `src/l4/api/api_handler.py:31`、`config/praxis.yaml`、`src/l1/kernel/params/api.py` |
| W2.2 | `set_harness_mode`/`set_security_mode`：posture-matrix 校验失败 → 拒绝（移除 try/except + logger.debug 继续） | `src/l3/tool_system/harness.py:83`、`src/l3/tool_system/security_mode.py` |
| W2.3 | boot 接线 `register_tools(TOOL_REGISTRY 全部名字)`，使 G1 白名单非空；governed 模式下空白名单 → BLOCK（仅显式 minimal/dev 允许 WARN） | `src/l3/boot/boot_steps/constitution.py`、`src/l1/kernel/gatechain.py:325`、`src/l3/tool_system/tool_config.py` |
| W2.4 | G2 升级：`identity_verified` 对 RING≥2 能力为必填（WARN→BLOCK），阈值走配置；identity 服务已能 `mark_identity_verified`，接上即可 | `src/l1/kernel/gatechain.py:339`、`src/l3/services/identity.py:174` |

**风险**：W2.1 改变安全默认值，需在 `config/praxis.yaml` 给出默认 token/显式开关并更新文档与相关测试。

## 3. WS3 — 进程状态机驱动 + 取消原语

| 子项 | 改动 | 文件 |
|---|---|---|
| W3.1 | 终端/卡片执行路径驱动 PCB：开始 `pt.set_running(agent_id)`、结束 `pt.exit(agent_id, code, reason)`；`ps` 输出真实状态 | `src/l3/agent_terminal/card_execution.py:174`、`src/l1/kernel/process.py`（新增辅助方法） |
| W3.2 | Kernel 取消：`process.cancel(agent_id)` 置 PCB 状态 + 发信号；agent_loop 每轮检查 `pt.is_cancelled()`；card cancel 统一走它 | `src/l1/kernel/process.py`、`src/l1/kernel/interrupt.py`、`src/l3/agent/agent_loop.py`、`src/l3/card/card_registry.py:346` |
| W3.3 | 长生命周期句柄登记：`l3/services/process.py` 与 `l2/shell_session.py` 的 Popen 在创建时 `ProcessTable.register_handle()`（仅登记，不改执行） | `src/l3/services/process.py:66`、`src/l2/shell_session.py:31`、`src/l1/kernel/process.py` |

**验收**：`main.py ps` 展示 READY/RUNNING/DONE/ZOMBIE 真实流转；取消后 agent 下一轮停止；句柄可枚举。

## 4. WS4 — 持久审计 + 事件收敛

| 子项 | 改动 | 文件 |
|---|---|---|
| W4.1 | kernel 审计落盘：`record_audit` 同时 append 到 `persist.py` journal（事件类型 `audit.syscall`），内存 deque 仅作查询 | `src/l1/kernel/__init__.py:116`、`src/l1/kernel/persist.py` |
| W4.2 | 每次工具调用（含被拒）强制 `record_audit("tool.invoke", ...)`：pipeline 与 invoke_gated 内统一记录 | `src/l3/tool_system/tool_pipeline_steps.py:260`、`invoke.py` |
| W4.3 | 事件收敛：冻结 `SignalType` 新增；kernel 提供字符串事件 schema 注册表（owner 字段），L3 各 bus 的事件名登记于此；文档化 ordering 契约（同 channel FIFO，跨 channel 无序） | `src/l1/kernel/event.py`、`src/l1/kernel/schema.py`（新） |

## 5. WS5 — Kernel 表面收缩（机制/策略分离）

> 大重构，逐个模块独立合入，每步保留过渡 shim 并同步 layer-import allowlist。

| 子项 | 改动 | 目标位置 |
|---|---|---|
| W5.1 | 域端口移出 kernel：CardRegistryPort / MonitorBusPort / I18nPort / LLMPort / CandidateLedgerPort | `src/l3/ports.py`、`src/l4/ports.py`（新） |
| W5.2 | `model_registry.py` 移至 L4 llm（过渡期 kernel 保留 re-export） | `src/l4/llm/model_registry.py` |
| W5.3 | `commands.py` → L2；`diff_frame.py` → L4 sandbox；`prompts.py` → L3 agent | `src/l2/`、`src/l4/sandbox/`、`src/l3/agent/` |
| W5.4 | params 拆分：AGENT_*/CARD_GATE_*/REVIEW_*/SCOUT_*/DIFF_*/SECURITY_GATE_*/API_* 业务常量迁往 `config/discovery/*.yaml` 或 L3/L4 参数模块；kernel params 只留 sync/allocator/gatechain/event/process 机制常量 | `src/l1/kernel/params/*.py`、`config/discovery/` |
| W5.5 | VFS 二选一：真正接线（fs_adapter 经 VFS mount 检查）或标记废弃并删除"所有文件操作都走 VFS"声明 | `src/l1/kernel/vfs.py`、`src/l3/services/fs_adapter.py` |

## 6. WS6 — 能力接口与调度契约（Rust 替换位）

| 子项 | 改动 | 文件 |
|---|---|---|
| W6.1 | 新增 `src/l1/kernel/capability.py::invoke_capability(agent_id, name, args, ctx)`：能力查找 → constitution → gatechain → allocator 记账 → 审计 → 适配器分发；ToolPipeline 变为其薄封装，所有执行器只调这一个函数 | `src/l1/kernel/capability.py`（新）、`src/l3/tool_system/tool_pipeline.py` |
| W6.2 | 定义 `KernelSchedulerPort`（submit/poll/yield/preempt 机制接口）进 kernel ports；L3 `CentralScheduler` 实现之；主路径经 port 调用（Rust 可替换机制） | `src/l1/kernel/ports/`、`src/l3/scheduler/scheduler.py` |
| W6.3 | 契约快照：`tests/infra/test_kernel_contract_snapshot.py` 生成并校验 kernel 公开 API 黄金 JSON（模块/类/函数/syscall），供 `l1_kernel_rs` 对齐 | `tests/infra/test_kernel_contract_snapshot.py`（新） |

## 7. 分期与顺序

| 阶段 | 内容 | 规模 |
|---|---|---|
| Phase 0 | WS1 + W2.1 + W2.3 + W4.2（封绕过、闭鉴权、填白名单、强制审计） | 1–2 个 session，可独立合入 |
| Phase 1 | WS2.2/2.4 + WS3 + W4.1/4.3（fail-closed 全面化、进程 FSM、持久审计、事件收敛） | 2–3 个 session |
| Phase 2 | WS5 + WS6（kernel 表面收缩、能力接口、调度 port、契约快照） | 每模块一个分支，逐个合入 |

每阶段完成标准：ruff / layer-import / params-compliance / 全量测试绿；新增测试覆盖；文档随代码同 commit（含本计划更新）；`verify-completion.sh` 出 COMPLETE 才收口。

## 8. 验收标准（全部达成即视为 Rust-ready）

1. 静态测试禁止 kernel 外任何直接 handler 调用；全仓库工具执行只经 `invoke_gated`/`invoke_capability`。
2. 无任何执行路径缺少审计记录（含被拒调用）。
3. API 鉴权默认关闭；harness/posture 失败即拒绝。
4. G1 白名单 boot 后非空；G2 对 RING≥2 强制身份验证。
5. `ps` 展示真实 PCB 状态流转；取消是 kernel 原语且生效。
6. kernel 公开 API 有黄金快照文件，`l1_kernel_rs` 可逐项对齐。
7. `params/` 仅含机制常量；域端口、prompts/skills/model registry/commands 全部不在 kernel 命名空间。

---

**规划结束。** 实施时按仓库 worktree 门禁在 `feature/*` 分支进行（每阶段一个分支）；本计划归档于 `docs/design/`，路线图登记见 `docs/roadmaps/README.md`。