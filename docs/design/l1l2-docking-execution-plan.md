---
pointer: DESIGN-2026-08-27-005
Fonds: DESIGN
series: active
date: 2026-08-27
status: active
title: "L1↔L2 对接执行计划（施工级）"
---

# L1↔L2 对接执行计划（施工级）

> Status: active execution plan · D2 首片及故障恢复片已在 `feature/ts-rust-e2e-docking` 完成 · 关联路线图: `docs/roadmaps/l1-l2-docking.md`
> 治理: 全部工作在独立 worktree 分支递进提交；完成后统一合入集成分支
> `feature/l1l2-integration`；**Diff 审查后须经操作员批准方可合入本地 main——未批准不得合入。**

## 0. 分支拓扑与合并纪律

```
main ──┬─→ feature/l1l2-integration（集成分支，主树挂载）
       │        ↑ 逐里程碑 --no-ff 合入（每合必跑分支门禁）
       │        │
       ├─ praxis-d0-parity    → feature/rust-outbox-parity        (D0)
       ├─ praxis-d1a-session  → feature/rust-host-session-fsm     (D1a ∥)
       ├─ praxis-d1b-outbox   → feature/rust-host-outbox-registry (D1b ∥)
       ├─ praxis-d1c-dispatch → feature/rust-host-dispatch        (D1c)
       ├─ praxis-d1d-hostbin  → feature/rust-protocol-host-bin    (D1d)
       └─ praxis-d2-seam      → feature/ts-rust-e2e-docking       (D2)

最终: integration Diff 审查 → 操作员批准 → --no-ff 合入本地 main
```

依赖序：D0 →（D1a ∥ D1b）→ D1c → D1d → D2。所有 worktree 从集成分支分叉
（含 rust scope 注册），保证钩子门禁全程可用。

## 1. 前置：rust scope 注册（集成分支首两个提交）

| 提交 | 内容 | 门禁动作 |
|---|---|---|
| C1 | `chore(config): register rust scope for Rust engine tree` | commits.yaml `scope_dirs.rust: systems/rust-kernel-engine/` + scopes 列表 + ALIGNMENT 行 + gen_commits_json 刷新（同提交） |
| C2 | `docs(design): add l1l2 docking execution plan` | 本文档落位 |

## 2. 各分支提交序列（规范化提交信息）

### D0 — feature/rust-outbox-parity（S，1–2 天）

| # | 提交信息 | 内容 |
|---|---|---|
| 1 | `test(rust): add multi-view replay regression vectors` | 先写失败测试：视图 A ack 不抹除视图 B 重放窗口（TDD 红灯） |
| 2 | `fix(rust): make Outbox ack non-destructive cursor advance` | protocol.rs ack 移除 pop_front，仅单调推进 last_acked |
| 3 | `feat(rust): add shared watermark parity with python host` | 共享水位=最落后视图语义（_advance_shared_cursor 镜像） |
| 4 | `test(rust): pin canonical json golden vectors vs python host` | Python host 输出冻结为参考向量，Rust 逐字节复现 |
| 5 | `chore(rust): unify seq bounds and wraparound edges` | u64/i64 边界审查 + maxSeq 回绕用例；wire 统一 safe-integer 上界，Rust 内部仍可保留 u64 |

退出条件：cargo test/clippy 干净 + 向量绿 + 多视图重放零漂移。

### D1a — feature/rust-host-session-fsm（M，2–3 天）∥

| # | 提交信息 | 内容 |
|---|---|---|
| 1 | `feat(rust): add session identity triple separation` | terminal_id/session_id/process_id 三分离类型（对齐 P0.1） |
| 2 | `feat(rust): add session lifecycle fsm` | Created/Ready/Running/Paused/Closing/Stopped/Failed 状态机 |
| 3 | `feat(rust): add view registry with attach/detach` | 会话内多视图注册表 |
| 4 | `test(rust): pin session lifecycle golden vectors` | 身份/生命周期向量钉 |

### D1b — feature/rust-host-outbox-registry（M，2–3 天）∥

| # | 提交信息 | 内容 |
|---|---|---|
| 1 | `feat(rust): add per-session outbox registry` | 会话级 outbox 表（复用 D0 修复后 Outbox） |
| 2 | `feat(rust): add per-view ack cursors` | SessionCursor 注册表 + 单调游标 |
| 3 | `feat(rust): add bounded eviction metrics` | 淘汰/容量计数器（可观测性） |
| 4 | `test(rust): add concurrent attach ack replay stress` | 并发压测零漂移 |

### D1c — feature/rust-host-dispatch（L，4–6 天）

| # | 提交信息 | 内容 |
|---|---|---|
| 1 | `feat(rust): add envelope routing skeleton` | KIND 分派骨架（command/control/ack/intent/event） |
| 2 | `feat(rust): wire command dispatch through capability gate` | 命令经 gatechain+capability 裁决 |
| 3 | `feat(rust): gate system commands by ring metadata` | `$`(__system) ring/danger 元数据强制——B4 关闭载体 |
| 4 | `feat(rust): persist audit records for every dispatch` | 含拒绝路径的审计落盘（audit.rs 接线） |
| 5 | `feat(rust): forward intent traffic to l3 upstream pipe` | L3 透传管道（分流路由原则） |
| 6 | `test(rust): pin dispatch matrix and rejection audit vectors` | 全 KIND 矩阵 + 拒绝审计向量 |

### D1d — feature/rust-protocol-host-bin（S，1–2 天）

| # | 提交信息 | 内容 |
|---|---|---|
| 1 | `feat(rust): add stdio host loop mirroring python contract` | 应答循环镜像 `python -m l2.protocol` I/O 契约 |
| 2 | `test(rust): cross-validate io contract against python host` | 双 host 同输入等价输出互验 |
| 3 | `feat(rust): expose frame limit contract constant` | 帧上限契约钉（对齐 TS/python） |

### D2 — feature/ts-rust-e2e-docking（S–M，2–3 天）

> 首片及故障恢复片已落地：host 工厂、环境开关、UTF-8 帧上限、双 host e2e、三向量
> canonical 互验和 child/input 断开即时失败均已提交到本分支；Rust 仍为 opt-in candidate，未接生产 boot/Port。

| # | 提交信息 | 内容 |
|---|---|---|
| 1 | `feat(l2): add PRAXIS_RUST_HOST transport switch` | TS e2e spawn 开关 |
| 2 | `test(l2): run engine e2e matrix against rust host` | 双 host 测试矩阵全绿 |
| 3 | `test(l2): add three-way envelope equivalence harness` | Py-host/TS/Rust 三方向量互验 |
| 4 | `fix(l2): fail pending requests on host disconnect` | child/input 断开、主动 close、合成协议故障帧即时结束；非法预算构造拒绝 |

### G4 前置片（2026-08-26）

| 交付 | 内容 | 当前边界 |
|---|---|---|
| Rust session-store codec | TS typed codec、原子文件适配器、共享 checkpoint fixture；严格校验版本、状态、序列、排序和安全整数 | 已落分支；只读/显式写入 Rust-owned checkpoint，不接生产 boot |
| G4 进程级互验 | test-only `rust-session-store-probe` + TS `session-store.e2e.test.ts`：Rust 写出→TS 读取、TS 写出→Rust 读取、错误版本拒绝 | 已落分支；probe 构建后分片绿，不接生产 boot/Port |

## 3. 每分支统一验证门

```bash
cargo test --workspace && cargo clippy -- -D warnings   # Rust 分支
npx tsc --noEmit && npx vitest run                      # D2 分支
bash scripts/sh/gate-merge.sh local                     # 合回集成前
```

## 4. 合并节奏与批准门

1. 每分支完成 → 分支门禁绿 → `--no-ff` 合入 `feature/l1l2-integration`
2. 全部合完 → 集成分支全量验证（Rust+TS+Python 快速套件）
3. 出具 Diff 摘要报告（文件×净增×语义分组）
4. **等待操作员批准 → 方可 `--no-ff` 合入本地 main；未批准不动**
