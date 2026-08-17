# Praxis Kernel Boundary Audit — Rust 重写前置基线

> 状态：规划（审计基线，尚未实施）
> 关联：`docs/roadmaps/frontend-kernel-roadmap.md`（Rust 下沉内核）、`docs/roadmaps/multilang-migration.md`（Rust kernel 槽位）、`docs/architecture/l1-kernel.md`（Rust-sink readiness）
> 目的：在 Rust 重写 L1 之前固定 Kernel 边界判定，避免把当前 Python 内核的错误边界、绕过路径与 fail-open 行为**原样复制进 `l1_kernel_rs`**。

---

## 0. 关键证据事实

| # | 事实 | 位置 |
|---|---|---|
| E1 | `syscall()` 生产环境 0 调用者（唯一调用在 `tests/integration/test_integration.py:47`）；`register_syscall()` 外部 0 使用者；内置 8 组 ~23 个子操作 | `src/l1/kernel/__init__.py` |
| E2 | 上层（L2–L5）对 kernel 的直接 import 共 1,104 处，全部绕过 syscall 直改内核状态 | 全量 grep |
| E3 | 三套互相独立的进程/卡片注册表：kernel `ProcessTable`、L3 `IssueTable`、L3 `CardRegistry` | `l1/kernel/process.py`、`l3/card/issue.py`、`l3/card/card_registry.py` |
| E4 | Kernel 无任何 scheduler 模块；调度在 L3 `CentralScheduler` + L4 `CronScheduler`，主路径仅 best-effort（try/except + debug 吞掉） | `src/l3/scheduler/`、`src/l3/cell/components/cell_execute.py` |
| E5 | 主 agent 路径经 L3 ToolPipeline 门禁（`agent_loop.py:_wrap_handler`），但存在多条不经 pipeline 的执行路径（见 §5） | `src/l3/agent/agent_loop.py:367` |
| E6 | G1 白名单从未填充：`register_tools()` 生产零调用；空白名单 → G1 = WARN；`test_unknown_tool_g1_blocks` 只断言 `allowed is not None` | `src/l1/kernel/gatechain.py:325`、`tests/l1/test_gatechain.py:163` |
| E7 | G2 身份校验仅 WARN（no Ed25519 keypair）；进程表 FSM 无人驱动 run/yield/exit | `src/l1/kernel/gatechain.py:339` |
| E8 | API 鉴权默认开放：无静态 token 且无 AuthPort → 放行；AuthPort 失败回退静态 token；空 token → True（backward-compatible open default） | `src/l4/api/api_handler.py:31-66` |
| E9 | harness 姿态检查 fail-open：posture matrix 校验包在 try/except + logger.debug | `src/l3/tool_system/harness.py:83` |
| E10 | VFS 文档声称唯一文件通路，实际仅 boot 步骤 + 2 个 L2 命令使用；真实 I/O 走 `l3/services/fs_adapter.py`（直接 OS）与 L4 sandbox | `src/l1/kernel/vfs.py:1-15` |
| E11 | Kernel 审计为内存 deque（maxlen、无持久化）；RC/审计在 L3（`reference_channel.py`），异步 best-effort | `src/l1/kernel/__init__.py:73` |
| E12 | 事件系统多头：kernel EventBus/SystemBus/IpcBus + L3 L3B/task_bus/monitor_bus/observability_bus/error_bus；`SignalType` 多成员无生产 emitter，字符串事件与枚举命名分裂 | `src/l1/kernel/event.py` |
| E13 | 危险工具 `execute_shell`/`destroy_file`/`deploy`/`run_code` 标注 requires witness approval，但该批准仅 pipeline 内生效 | `config/tools.yaml` layer_3 |

## 1. Kernel Boundary Map（当前职责归属）

| 合法 Kernel 职责 | 模块 | 为什么属于 Kernel |
|---|---|---|
| 同步原语 | `sync.py` | Mutex/Semaphore/Barrier/RWLock 机制 |
| 进程表 + PCB FSM | `process.py` | 生命周期记账（但非权威，见 §3） |
| 内存/token 记账机制 | `allocator.py`、`resource.py` | alloc/free/quota 机制 |
| 工具授权链机制 | `gatechain.py` | G1–G5 引擎（enforcement 实际组装在 L3） |
| 宪法规则引擎 | `constitution.py` | 最高权威机制（规则内容部分外置 `.praxis-rules.md`） |
| 事件发布/订阅原语 | `event.py` | kernel EventBus |
| 组件生命周期总线 | `bus.py` | SystemBus install/init/start/stop |
| Port 抽象 | `ports/` | 六边形接缝（类型） |
| IPC 原语 | `ipc.py`、`channel_ring.py` | LockChannel / ChannelPort |
| IRQ 表 | `interrupt.py` | 中断机制 |
| 线程池 | `worker_thread.py` | 计算机制 |
| OS 生命周期 | `os.py`、`lifecycle.py` | boot/shutdown/restart/watchdog FSM |
| 日志账本 | `persist.py` | SQLite 事件 journal |
| 错误归一化 | `errors.py` | 结构化错误码 |
| 路径/平台抽象 | `paths.py`、`platform.py` | OS 接缝 |
| 注册表基类 | `registry.py`、`registry_base.py` | 通用注册机制 |
| 版本/迁移 | `versioning.py`、`migration.py` | schema 版本机制 |
| 配置发现 | `discovery.py` | 结构化配置机制 |

## 2. Incorrectly Included（不应在 Kernel 的模块）

| 模块 | 原因 | 建议去处 |
|---|---|---|
| `prompts.py`（623 行） | prompt 模板/覆盖 = 内容/呈现策略 | L3 prompt 层 |
| `skill.py` + `skill_policy/guidance/retrieval/persist` | Skill 领域存储 + 进化策略（仅 write-gate 是安全机制） | L3 memory/skill 服务；kernel 只留 CapabilityPort 门 |
| `model_registry.py` | LLM provider 发现/注册 = provider 关注点 | L4 llm |
| `reputation.py` | G5 信任评分 = 策略 | L3 策略，注入 G5 |
| `commands.py` | shell 命令注册表 = UI/CLI 逻辑 | L2 |
| `diff_frame.py` | sandbox diff 帧编码 | L4 sandbox |
| `net.py` / `net_transport.py` | 跨 Cell UDP/TCP/TLS 传输细节 | L4 transport；kernel 只留 IPC 原语 |
| `notify.py` | 监督/通知策略 | L3 services（NotifyPort 可留） |
| `identity_binding.py` | 角色→prompt 片段绑定 = 组织策略 | L3 identity |
| `params/system.py` | REVIEW_*/SCOUT_*/DIFF_*/SECURITY_GATE_SCORE_*/RESULT_STORE_* 业务常量；`PERF_HARNESS_*` 构建采样常量 | L3/L4 config；`PERF_HARNESS_*` → `config/quality`/构建脚本 |
| `params/agent.py` | BUILTIN_RULE_DEFS/AGENT_CLEARANCE/AGENT_PRIORITY/AGENT_ROLE_MAP/CARD_GATE_*/TERRITORY_MAP/reputation 权重 | config/policy 层 |
| `params/api.py` | API 分页/token/WS/RPC 常量 | L4 config |
| `SignalType` 业务成员 | Card/批准/工具域事件写进 kernel 枚举 | L3 事件 schema；kernel 留通用 string/channel 原语 |
| `InterruptType`（AGENT_CRASH/RESOURCE_EXHAUSTION…） | Agent 域中断分类 | L3；kernel 留裸 IRQ 机制 |

## 3. Incorrectly Excluded（应下沉到 Kernel 却留在上层的职责）

| 职责 | 现在在哪 | 风险 | 应下沉到 |
|---|---|---|---|
| 调度机制（队列/优先级/时间片） | L3 CentralScheduler + L4 CronScheduler；主路径无调度 | 无系统级调度权威；多执行器竞争 | Kernel scheduler 原语（策略=上层） |
| 单一执行权威 | L3 ToolPipeline 组装 | 多条无门禁执行路径（§5） | Kernel invoke capability syscall；pipeline 成唯一执行器 |
| 工具能力注册表 + ring/danger 强制 | L3 ToolSpec/ToolConfig + G1 白名单从未填充 | G1 是 no-op；enforce 靠约定 | Kernel capability registry（config 供给） |
| 长生命周期进程句柄 | `l3/services/process.py`、`l2/shell_session.py` | Kernel 失去句柄所有权 | Kernel ProcessPort/进程表拥有所有句柄 |
| Agent 取消原语 | L3 agent_loop_guard/card cancel；kernel interrupt.py 未接执行 | 取消 best-effort | Kernel 取消令牌 + PCB 状态机 |
| Checkpoint/恢复权威 | `l3/boot/boot.py` + 各子系统 JSON | 内存/磁盘状态分裂 | Kernel checkpoint/restore 权威状态 |
| 统一事件/消息通道 | L3B/task_bus/monitor_bus/observability_bus 与 kernel EventBus 并存 | 无权威 owner；ordering 未定义 | Kernel channel 原语；L3 只留业务 schema |
| 追加式审计权威 | kernel 审计=未用内存 deque；RC=L3 异步 recorder | 审计可绕过、非持久 | Kernel 追加式审计，每次 capability 调用强制写入 |
| 请求边界鉴权 | `_auth_ok` 默认开放；L3 central_security 仅 advisory | fail-open 信任模型 | Kernel capability 检查先于任何外部请求 |

## 4. Missing Invariants（缺失的 Kernel 不变量）

| 不变量 | 文档声称 | 实际 enforcement | 绕过 | 有测试? |
|---|---|---|---|---|
| 所有工具调用走同一授权链 | Every operation goes through syscall()、G1–G5 non-bypassable | 仅 AgentLoop 包装后的 ToolPipeline | L2/MCP/裸 handler 完全跳过 | 无 |
| G1 白名单拦截未知工具 | gatechain doc | register_tools() 零调用 → G1 WARN | 空白名单=WARN 非 BLOCK | 弱 |
| 进程状态机权威 | process.py FSM | 无人驱动 run/yield/exit | L3 CardRegistry/ExecutionPlan 才是真生命周期 | 部分 |
| 执行前身份验证 | G2 | 仅 WARN | identity_verified 从不被要求 | 无 |
| API 默认关闭 | central security gate decides | 无 token/无 port → True | 无 token 请求放行 | 无 |
| VFS 是唯一文件通路 | vfs.py docstring | VFS 无人用；fs_adapter 直接 OS | 处处直写文件 | 无 |
| 宪法/gatechain 施加于每个动作 | Will cannot violate the constitution | 仅逐工具 pipeline 检查；loop 级注入 non-fatal | MCP/L2/sideload | 部分 |
| 资源记账覆盖所有计算 | allocator/limiter | 仅 pipeline 路径；LLM worker/线程池/会话/scout 不在账 | 处处并行池 | 无 |
| harness/posture 失败即关闭 | security-evidence doc | try/except + debug 继续 | posture matrix 不可用即放行 | 部分 |
| Kernel 状态原子持久/可恢复 | persist.py | 碎片化 JSON owner | 各模块自管 | 部分 |
| 单一时间源 / 事件有序 | — | wall clock 与 monotonic 混用；异步线程池 | ordering 未定义 | 无 |
| 审计强制且持久 | syscall audit doc | 内存 deque；RC 异步 best-effort | 无门禁路径不记录 | 无 |

## 5. Bypass Paths（绕过路径）

| # | 路径 | 严重度 | 为何绕过 Kernel | 修复 |
|---|---|---|---|---|
| B1 | L2 shell _run_tool → execute_tool_spec（`l2/shells/terminal.py:248-253`） | CRITICAL | execute_tool_spec 直接跑 handler，无 gatechain/constitution/approval/sandbox；RING_3 execute_shell 丢失 witness approval | 全部改走 ToolPipeline；execute_tool_spec 降为私有 helper |
| B2 | POST /api/v2/mcp/tools/call → _dispatch_tool（`l4/api_handlers/api_handlers_mcp.py:413-427`） | CRITICAL | 同一无门禁执行，暴露于 HTTP；鉴权默认开放 | pipeline + kernel capability 检查 + 关闭默认开放 |
| B3 | LLMEngine.tool_use → _execute_one_tool → tool_def.handler（`l4/llm/llm_tools.py:22-35`） | HIGH | 未包装 ToolSpec 直接执行裸 handler（执行语义在 L4） | 拒绝未包装 spec；仅构造点包装 |
| B4 | L2 shell ! 命令 → get_process_port().run（`l2/shells/terminal.py:_system_result`） | HIGH(user)/MEDIUM(agent) | 进程执行无 gatechain/constitution | 按 ring 门禁 shell 命令 |
| B5 | POST /api/v2/cards/sideload → cell.execute_card（`l4/api/api_handlers_cards.py:sideload_dispatch`） | HIGH | outside the card pipeline 明言跳过批准 | 删除或走同一链条 |
| B6 | `l3/services/process.py` + `l2/shell_session.py` 长生命周期 Popen | MEDIUM | 句柄游离于 ProcessPort/进程表 | Kernel 拥有进程句柄 |
| B7 | API 工厂重置/reload/harness 切换（system_reset/system_reload/security handlers） | HIGH | 默认开放鉴权下可清空/改写系统状态 | 系统变更走 kernel capability + 审计 |
| B8 | L3A 会话直接调 handler（`l3/cell/peers/l3a/session_loop.py:97`） | MEDIUM | handler 级捷径不经 pipeline | 仅限系统内部、agent 不可达 |
| B9 | syscall()/register_syscall（`l1/kernel/__init__.py`） | LOW（死代码） | agent_id 自报可伪造；任意注册无授权检查 | 删除或重建为唯一 capability 门 |

## 6. Mechanism / Policy Conflicts

- gatechain.py：机制在 kernel，danger 等级/风险阈值/频率乘数为 params 常量 = 策略硬编码。
- allocator/resource：机制在 kernel，按角色 profile 来自 params/agent.py = 角色策略。
- event.py：总线机制在 kernel，SignalType 成员 = 业务事件语义。
- constitution.py：引擎在 kernel（规则外置 .praxis-rules.md，对），但 BUILTIN_RULE_DEFS 重复内嵌规则。
- 工具执行：机制（pipeline 组装）在 L3，kernel 只提供库 → 可执行决定权在 L3 且可被跳过。
- 调度：机制缺失于 kernel；CentralScheduler 在 L3 混合机制与策略。
- harness/security-mode：策略在 L3 且 fail-open；kernel 经注入 provider 获知策略 → 安全底线依赖 L3 wiring。

## 7. Abstraction Leakage

- ports/service.py：CardRegistryPort/MonitorBusPort/I18nPort/LLMPort/CandidateLedgerPort 领域类型端口进 kernel。
- net_transport.py：TLS/TcpAdapter 传输细节进 kernel。
- prompts.py：内容进 kernel。
- SignalType/InterruptType：agent 域名进 kernel。
- params/api.py、params/system.py：HTTP/业务常量进 kernel。
- Kernel 接受大量 L3/L4 注入回调（bind_cell/set_persist_handler/set_posture_provider/set_harness_provider/error capture/swapper←MemoryService）→ 权威路径依赖上层 wiring，失败即降级（fail-open）。

## 8. Dependency Direction

- 静态 import：L1 → 上层干净（src/l1 无 from l3/l4 语句）。
- 但 tests/infra/test_layer_imports.py 无条件 allowlist (1,3) 与 (1,4) 模式——向上 import 重新引入不会被拦。
- 动态/注入耦合：kernel → L3/L4 回调（§7），属 Kernel → Application 注入形态，多处 fail-open。

## 9. Kernel Surface Area

- 现状：66 文件 / ~19.3k 行；8 组 syscall（死代码）；~15+ Port ABC；SignalType(20)；EventBus/SystemBus/IpcBus；ProcessTable；Allocator；Limiter；GateChain；Constitution；VFS；persist journal；worker pool。
- 可删除：syscall()+register_syscall（或重建为唯一 capability 门）；VFS（或真正启用）；G1 白名单管道（直到 register_tools 被接线）。
- 必须保留（机制）：sync、event 核心、process 表（重新驱动）、allocator 核心、limiter 核心、gatechain 引擎、constitution 引擎、ports 类型、worker_thread、os/lifecycle、persist journal、errors、paths、platform、ipc/channel_ring、interrupt、territory。
- 应拆分：params/；gatechain（引擎 vs 阈值）；EventBus（原语 vs 业务信号）；process（表 vs 真生命周期驱动）。
- Kernel Primitive Set：sync、event-channel、process、alloc/free、invoke-capability、check-constitution、check-gatechain、audit-append、checkpoint/restore、ipc-send/recv、worker-submit、irq-raise、path-contains。
- Non-Kernel API Set：prompts、skills、model registry、command registry、diff frames、net transport、notify、reputation 策略、identity bindings、scheduler 策略、card/issue 注册表、approval gates、tool registry、harness/security-mode。

## 10. 结论与评分

**Kernel Boundary Integrity Score：42/100**（40–59：Kernel 事实上已变成大型 Core Framework）。

理由：syscall 死代码 + 1,104 处直接 import；执行权威在 L3 且有 CRITICAL 绕过（B1/B2）；调度器不在 kernel；G1 未填充/G2 仅 WARN/API 默认开放/harness fail-open；kernel 内装 ~6 个领域子系统；持久化/审计/事件碎片化。

值得保留：ports 抽象、宪法引擎+外部规则数据、gatechain 崩溃即 BLOCK、lifecycle FSM、harness bottom-line 测试、layer-import 门禁、agent-loop pipeline 包装。

## 11. Minimal Kernel 与 Rust 重写落地顺序

### 11.1 Minimal Kernel（Rust 重写应携带的边界）

留下（真正不可绕过的核心）：sync、event 核心（无类型 channel+pub/sub）、process（ProcessTable+真实 FSM+取消令牌，拥有所有句柄）、allocator/resource（仅记账，profile 注入）、gatechain（引擎，阈值/白名单注入，boot 时填充）、constitution（引擎，规则只从数据加载）、**invoke-capability syscall（唯一执行门：register/authorize/invoke/audit）**、ports 机制类型、worker_thread、os/lifecycle、persist journal、errors、paths、platform、ipc/channel_ring、interrupt、territory、versioning/migration、discovery。

移出：prompts、skill*、model_registry、reputation、commands、diff_frame、net/net_transport、notify、identity_binding、scheduler 策略、card/issue 注册表、approval gates、tool registry、harness/security-mode 策略。

唯一入口：invoke_capability / audit_append / register_process+cancel_process / emit_event+on_event / check_constitution+check_gatechain / checkpoint+restore。

Kernel 强制不变量：单一执行器；G1 白名单非空（未知能力=BLOCK）；G2 身份验证（WARN→BLOCK）后 RING≥2 才可执行；进程生命周期闭环（终止后不可执行）；每次 invoke 记账（超限=BLOCK）；每次 invoke 追加持久审计；任何 gate/wiring 失败=BLOCK（fail-closed）；单一事件通道。

### 11.2 Rust 落地顺序（与 frontend-kernel-roadmap M3/M4 衔接）

1. **Phase 0（Python 侧封口，先于任何 Rust 迁移）**：修复 B1/B2/B3 绕过与 E8/E9 fail-open；`register_tools()` 接线使 G1 白名单非空；把 execute_tool_spec 降为仅 pipeline 可调。
   - ✅ **已实施（feature/kernel-boundary-hardening）**：B1/B2 改走 `invoke_gated`（单一执行门，交互主体经 `interactive` 过 G2，G1/G3/G4/G5 照常）；B3 拒绝未包装 spec（`ToolSpec.gated`）；B5 sideload 改走 CardRegistry.submit；E8 API 鉴权默认关闭（`AUTH_DENY_WHEN_UNCONFIGURED`，`PRAXIS_AUTH_OPEN=1` 显式开启）；W2.3 G1 白名单 boot 填充 + 空白名单 BLOCK（fail-closed）；W4.2 每次工具调用（含被拒）写入 kernel 审计。
2. **Phase 1（执行权威收敛）**：在 kernel 侧定义 invoke-capability 接口并让 AgentLoop/MCP/L2/LLM engine/sideload 全部改走它——Rust 重写才有单一可替换执行面。
   - ✅ **已实施（W6.1）**：`src/l1/kernel/capability.py::invoke_capability` 成为唯一执行权威——未接线 executor 即 fail-closed BLOCK + 审计；boot 唯一接线点把 kernel seam 连到 ToolPipeline（`_register_capability_executor` → `invoke_gated`）；L2 shell 与 MCP 边界调用方已全部改走 kernel seam。同时落地 W2.2（harness posture 校验失败即拒绝）与 W2.4（RING≥2 未验证身份 G2 BLOCK）。
3. **Phase 2（按缩放曲线选热路径，frontend-kernel-roadmap §4.2）**：优先 sync/event/allocator/process 记账等纯机制模块；只迁移机制，策略留在 Python/config。
4. **Phase 3（下沉验收）**：每个下沉模块必须满足——无 bypass、fail-closed、审计强制、白名单非空、port 接口不变（`l1_kernel_rs` 复用同一套 params/ 常量）。
5. **重审门槛**：每迁移一个模块前重跑本审计 §4 不变量清单；任何在 Python 侧靠约定维持的不变量不得进入 Rust 侧。

> **实施计划**：`docs/design/rust-readiness-hardening-plan.md`（WS1–WS6，Phase 0–2，全部为 Python 侧封口，不写 Rust）。

---

**规划结束。** 本文件是审计基线而非施工计划；施工计划按 `docs/roadmaps/README.md` 管理规则放 `docs/design/`。
