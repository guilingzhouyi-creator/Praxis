---
pointer: ROADMAP-2026-08-23-010
archive_number: ROADMAP-2026-长期-010
fonds: ROADMAP
year: 2026
retention: 长期
title: "L1 ↔ L2 对接计划（TS-L2 × Rust-L1 Wire Docking）"
author: L3
formation_date: 2026-08-23
carrier: md
classification: 内部
pages: 138
archivist: L3
reviewer: L3
archive_date: 2026-08-29
source: roadmap
keywords: []
abstract: "将 TS 引擎（终态 L2 权威）与 Rust 内核（终态 L1）经协议 v1 线缆直接对接，"
series: active
date: 2026-08-23
status: active
construction: in_progress
---

# L1 ↔ L2 对接计划（TS-L2 × Rust-L1 Wire Docking）

> Status: in progress（操作员 2026-08-23 确认方向：TS L2 为终态权威，承载上层会话接入面并对接 Rust L1 内核。
> 2026-08-26 复核：D0 语义修复与 D1a–D1d 机制候选已落 main；本分支已完成 D2 首片及故障恢复片——`PRAXIS_RUST_HOST` 选择器、受管 stdio child transport、双 host e2e、TS/Python/Rust canonical vector 互验，以及 child/input 断开时 pending 请求即时失败。D2 不改变生产默认（仍为 Python），Rust host 仍是 candidate-only、未接入 boot/Port。
> 关联: `l2-ts-rewrite-mapping.md` §5 割接标准 · `frontend-kernel-roadmap.md` §4 Rust 路线 ·
> `kernel-boundary-audit.md` 绕过路径清单 · `rust-first-kernel-rewrite.md` R0–R5 门槛 · 施工载体 `../design/l1l2-docking-execution-plan.md`
> 审查基线: main @ e1f0dc10（2026-08-23 深度审查结论）；复核基线 main @ 123b22d2

## 0. 目标与范围

将 TS 引擎（终态 L2 权威）与 Rust 内核（终态 L1）经协议 v1 线缆直接对接，
替代当前「TS → Python host → 进程内 L1」的两跳路径。**L3 归属不在本计划范围内**
（操作员裁定）；intent/L3A 流量仍转发至 L3 权威面，本计划只负责 L1 面操作的直连。

## 1. 现状：三个代码库、两条边界

| 边界 | 形态 | 状态 |
|---|---|---|
| Py-L2 ↔ Py-L1 | 进程内函数调用（~40 import 点：params ×12、capability ×2、ports/vfs/skill/process/event/identity_binding） | 今日生产路径；B4 绕过长于此 |
| TS-L2 ↔ Py-host | 协议 v1 线缆（stdio/http/ws/ssh） | ✅ 已通，e2e.stdio 验证 |
| **TS-L2 ↔ Rust-L1** | 协议 v1 stdio，`PRAXIS_RUST_HOST` opt-in | 🟡 D2 首片已通；默认仍 Python |

## 2. 审查发现（2026-08-23 深度审查）

| # | 发现 | 严重度 | 位置 |
|---|---|---|---|
| F1 | ~~Rust `Outbox::ack()` 破坏性弹出（pop_front），违反多视图非破坏性重放不变量~~ **✅ 已修复（落 main）**：`Outbox::ack` 改为 `last_acked` 单调推进的游标式非破坏 ack，per-view cursor 与共享水位=最落后视图已实现；多视图重放回归由独立测试域覆盖（`tests/storage/kernel_test_outbox_registry.rs`、`tests/session/kernel_test_session_lifecycle.rs`） | ✅ 关闭 | `systems/rust-kernel-engine/l1-kernel-rs/src/kernel_protocol.rs` |
| F2 | ~~Rust 侧只有协议验证门；`rust-protocol-gate` bin 为回声器~~ **✅ 已补齐（机制级）**：`host_dispatch.rs` 提供 KIND 逐类路由 + gatechain/capability 裁决 + ring 门控 `__system` 命令（边界审计 B4 在新边界的关闭载体）+ 审计接线 + L3 上游透传管道；`bin/rust-protocol-host.rs` 镜像 Python host I/O 契约（行协议、1 MiB 帧上限、stderr 错误通道）。仍未接入生产 boot/Port | 🟢 机制闭合 | `systems/rust-kernel-engine/l1-kernel-rs/src/host_dispatch.rs`、`systems/rust-kernel-engine/l1-kernel-rs/src/bin/rust-protocol-host.rs` |
| F3 | 地基成熟度超预期：约 68 个 Rust src 模块（session_store/gatechain/capability/audit/terminal/vfs/managed_process 全在），R4 assembly 有 bin 入口；TS transport 已可由环境选择 Python/Rust，且保留 child 生命周期与 stderr 隔离。协议 v1 跨语言 conformance 向量已从 TS 引擎冻结并由 Rust gate/Python reference 逐字节互验 | 🟢 利好 | `systems/rust-kernel-engine/l1-kernel-rs/src/`、`systems/typescript-shell-engine/src/engine/transports/rust-host.ts` |

## 3. 阶段计划 D0–D3

```
D0 语义修复 ──→ D1 Rust 协议主机 ──→ D2 TS↔Rust 缝合 ──→ G1–G6 割接阶梯
   (数日)          (主体工程)           (机械缝合)          (l2-ts-rewrite-mapping §5.3)
```

### D0 — 语义修复（前置阻断项）

> 状态（2026-08-26 复核）：D0.1 ✅ 游标式非破坏 ack；D0.2 ✅ 共享水位=最落后视图；
> D0.3 ✅ 协议 v1 conformance 向量已冻结并逐字节比对（参考源为 TS 引擎 normative fixture，
> 强于原 Python host 参考方案）；D0.4 ✅ seq wire 上界、回绕和三端边界向量已专项收口。

| 任务 | 验收 |
|---|---|
| D0.1 Rust `Outbox::ack` 改游标式非破坏性（消息保留，仅 last_acked 单调推进） | 多视图重放测试：视图 A ack 不抹除视图 B 重放窗口 |
| D0.2 共享水位 = 最落后视图语义对齐（`_advance_shared_cursor` 镜像） | 与 Python host 同输入产出相同游标序列 |
| D0.3 Golden vectors 冻结：Python host 输出为参考，Rust 门逐字节复现 canonical JSON 排序 | `tests/fixtures/kernel_*_vectors.json` 纪律扩展到 envelope 向量 |
| D0.4 seq 类型统一审查（u64/i64 混用、maxSeq 回绕边界） | ✅ wire seq/ack/recovery cursor 统一限制为 `2^53-1` safe integer；TS/Python/Rust 共用上界向量，生成计数器越界回绕到 1；Rust 内部仍可用 `u64` |

### D1 — Rust 协议主机（工程主体）

> 状态（2026-08-25 复核）：D1a–D1d 机制候选均已落 main——`session_identity.rs`（三分离身份）、
> `session_lifecycle.rs`（会话 FSM+视图注册表）、`outbox_registry.rs`（per-session outbox+per-view 游标）、
> `host_dispatch.rs`（KIND 路由+gatechain/capability 裁决+ring 门控 `__system`+审计+L3 透传管道）、
> `bin/rust-protocol-host.rs`（stdio host）。独立测试域覆盖路由矩阵、ring 门控系统命令（B4 新边界关闭载体）、
> R2/R4/R7 裁决、持久化审计行与 golden vector。仍未接入 boot/Port/生产入口，不解除 G3/G6。

| 子阶段 | 内容 | 复用 | 新建 |
|---|---|---|---|
| D1a 会话权威 | 会话注册表 + 生命周期 FSM（对齐 P0.1 身份模型 terminal_id/session_id/process_id 三分离） | session_store.rs | 会话 FSM + 视图游标管理 |
| D1b Outbox 权威 | 追加/淘汰/非破坏 ack/共享水位 | protocol.rs Outbox（D0 修复后） | per-session outbox 注册表 |
| D1c 命令分派 | envelope → capability 路由；ring/danger 元数据裁决；审计每次调用含拒绝 | gatechain.rs + capability.rs + audit.rs | 分派路由层 + `$`(__system) 命令的 ring 门包装 |
| D1d stdio 服务 | 应答循环镜像 `python -m l2.protocol` I/O 契约（行协议、帧上限、错误通道 stderr） | rust-protocol-gate bin | rust-protocol-host bin |

**架构红利**：`$` 系统命令走线缆时强制携带 ring/danger 元数据并由 Rust capability 门裁决——边界审计 B4 绕过在新边界上天然闭合。

### D2 — TS↔Rust 缝合（机械性）

> 状态（2026-08-26 复核）：🟡 首片已落本分支。`PRAXIS_RUST_HOST` 只在明确取值
> `1/true/yes/on/rust` 时启用 Rust；默认及未知值回到 Python。D2.3 的 1 MiB 上限已在
> TS line transport、Rust `protocol_host`、Python `ProtocolHost` 三侧固定；超限请求在
> TS 适配层先拒绝，避免把无 ack 的 DoS frame 写入 host。

| 任务 | 验收 |
|---|---|
| D2.1 `PRAXIS_RUST_HOST` 开关 + e2e 反转矩阵（TS engine spawn rust-host bin） | ✅ `e2e.stdio` 按开关选择双 host；Rust 独立 e2e 覆盖 command/attach/recovery |
| D2.2 三方向量互验：Py-host / TS / Rust 同输入等价 envelope 流 | ✅ fixture canonical lines 逐字节一致；Rust gate 与 Python reference 均纳入测试 |
| D2.3 帧上限契约钉（Rust/Python/TS） | ✅ 三端均为 1 MiB UTF-8 字节上限；TS 请求/响应边界测试与 Python 参考 host 超限前置解析测试已锁定 |
| D2.4 传输故障恢复语义 | ✅ child `error`/`exit`、stdio `close`、主动 `close()` 即时拒绝 pending；合成协议故障帧不再等待 ack；预算参数非法时构造即失败；重连仍由 `ConnectionManager` 显式触发 |

2026-08-30 补齐 Python 参考 host 的对齐切片：`handle()` 与 `run()` 共用
UTF-8 字节计量 helper，超限帧在进入 JSON 解码前即被拒绝；一条输入产生的
完整响应集合（例如 result + ack）只触发一次 flush。该优化不改变 Python
参考 host 的生产默认地位，也不提前满足 G5。

### G4 前置片（2026-08-26）

TS 已新增独立 Rust session-store codec 与原子文件适配器（`session-checkpoint.ts`），
严格镜像 Rust `SessionStoreDocument`、`SessionCheckpoint`、`SessionSnapshot` 的版本、状态、
序列和排序不变量；TS 无法精确表示的 `u64` 在边界 fail-closed。共享 fixture
`tests/fixtures/kernel_session_store_document.json` 已由 TS 编解码测试和 Rust
`session_store` 测试共同消费。新增 test-only `rust-session-store-probe` 后，TS
`session-store.e2e.test.ts` 在 probe 已构建时覆盖 Rust 写出→TS 读取、TS 写出→Rust
读取，以及 Rust 对错误版本的 fail-closed 拒绝。该片不改变 Rust host
candidate-only 状态；未构建 probe 时该进程级切片显式 skip，不伪造通过。

随后补齐 Rust execution checkpoint 的 TS 只读消费边界：
`execution-checkpoint.ts` 严格校验 `SessionBook`、`TerminalBook` 与
`AgentLoopBook` 的版本、排序、safe integer、clean/unclean 限制和跨表身份引用，
并只提供打开、刷新和 defensive snapshot，不提供 TS 写入、恢复或 rebind 权限。
共享 fixture `tests/fixtures/kernel_execution_store_document.json` 同时由 Rust
`execution_store` 测试和 TS codec 测试消费。该片仍不改变 Rust host 默认路径，
也不把 read-only projection 误当作 R5 cutover authority。

2026-08-30 补齐下一层 TS 终端投影：
`rust-agent-loop-terminal.ts` 镜像 Rust
`agent_loop_terminal::AgentLoopTerminalBridge` 的保留值合同，校验
loop/session/terminal 三元绑定、终端状态、流向、safe sequence、1 MiB
帧上限和 256 帧批上限，并复制 `number[]`/`Uint8Array`，避免前端别名
污染。未建立绑定、稀疏数组、非法字节、方向混用和身份漂移均
fail-closed。该投影只供 L2/前端渲染或转发，不读取/写入 Rust mailbox，
不解码 shell，不创建 PTY，不执行 AgentLoop/provider/tool；专测为
`tests/rust-agent-loop-terminal.test.ts`，Rust 证据仍为
`tests/session/kernel_test_agent_loop_terminal.rs`。

### 分流路由原则（D1c 核心）

| 流量 | 去向 |
|---|---|
| `$` system / process / fs / health / status 等 L1 面操作 | Rust host 直答（capability 门内） |
| `/engine` 命令、alias、补全 | TS 本地（纯解析/展示） |
| intent / L3A / card / memory / tool | 经线缆转发 L3 权威面（归属另定，本计划只做透传管道） |

## 4. 里程碑计划表

| 里程碑 | 交付物 | 退出条件 | 规模 | 依赖 |
|---|---|---|---|---|
| **M-D0** | feature/rust-outbox-parity 分支 | F1 修复 + 向量绿 + cargo test/clippy 干净 | S（1–2 天） | — |
| **M-D1a** | rust-host: 会话 FSM | 会话生命周期向量绿；身份三分离测试 | M（2–3 天） | M-D0 |
| **M-D1b** | rust-host: outbox 注册表 | 多视图并发 attach/ack/replay 压测零漂移 | M（2–3 天） | M-D0 |
| **M-D1c** | rust-host: capability 分派 | 全 KIND 分派矩阵 + 拒绝路径审计落盘；B4 关闭证据 | L（4–6 天） | M-D1a/b |
| **M-D1d** | rust-protocol-host bin | 与 python host I/O 契约互验绿 | S（1–2 天） | M-D1c |
| **M-D2** | TS↔Rust e2e 与故障恢复绿 | ✅ 双 host 测试矩阵、三方向量互验、child/input 断开即时失败全绿；生产默认未切换 | S–M（2–3 天） | M-D1d |
| **G1–G6** | l2-ts-rewrite-mapping §5.3 阶梯实例化 | 覆盖 ≥95/90 → 向量冻结 → 反转 e2e → 持久化互读 → 切默认+开关 → 移除旧 host | 按 §5.2 | M-D2 |

关键路径：D0 → D1a/D1b（可并行） → D1c → D1d → D2 ≈ **12–17 个工作日**（单 Agent 串行估算；D1a/b 并行可压缩 2–3 天）。

## 5. 风险登记册

| # | 风险 | 缓解 | 触发点 |
|---|---|---|---|
| R1 | seq 类型/回绕差异 | D0.4 向量用例 | 编码层 |
| R2 | 政策/机制冲突复制进 Rust（边界审计 §6：params 硬编码策略） | Rust 侧策略一律注入 + 快照驱动（rewrite 设计 §3.4） | D1c |
| R3 | L3 归属未定导致 intent 转发目标悬空 | D2 前由操作员裁定 L3 权威面；此前 D1 只建透传管道 | D1c→D2 之间 |
| R4 | 双 host 长期共存漂移（edc5caa6 教训） | golden vectors 已进 TS/Rust/Python slice；任何一侧改动必须同步向量 | 全程 |
| R5 | Rust host 性能未达 R2 证据即被误用于生产判断 | bench 结果标注 candidate-only（现有纪律延续） | M-D1d 后 |

## 6. 与既有路线图的接缝

- `l2-ts-rewrite-mapping.md` §5 割接标准：本计划 D2 完成即满足其 G3「反转 e2e」的 Rust 变体；§5.3 阶梯在 M-D2 后接管。
- `frontend-kernel-roadmap.md` §4：本计划是 §4.3 独立构建路径中「仅对保留的 TS/L2 边界定义版本化 wire contract」的落地实例。
- `production-closure-roadmap.md` P0.5/B4：D1c 的 ring 门包装即其修复载体。
- `agent-os-3x-closure.md` §5 约束：「TS owns no scheduler/AgentLoop/tool execution/memory promotion」在本计划的分流路由表中逐条成立。
