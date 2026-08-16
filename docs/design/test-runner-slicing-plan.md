# Test Runner Slicing Plan — Full Analysis

> Status: 方案（proposal，未实施）
> Scope: `tests/` 全库切片改造设计，覆盖 `tests/runner.py`
> Date: 2026-08-16

## 1. 现状画像（实测）

### 1.1 全库结构

| 顶层 | 测试文件数 | 说明 |
|------|-----------|------|
| tests/l3 | 292 | cell=34, agent=34, memory=53, services=25, tool_system=22, tools=19, l3a=18, card=13, bus=12, scheduler=11, boot=9, config=7, subagent=7, discussion=6, identity=4, error_bus=4, agent_terminal=4, session=3, cell/peers=11, l3a/peers=3 |
| tests/l4 | 91 | api_handlers=15, sandbox=11, api=7, adapters=7, vault/search/rpc/mcp/auth=3×5, lsp/llm_worker/misc=2×3, llm=1 |
| tests/l1 | 33 | 含 kernel/ports |
| tests/l2 | 23 | 含 l2_shell/commands |
| tests/infra | 22 | 门禁文件 |
| tests/integration | 12 | 跨层 |
| tests/l5 | 2 | — |
| tests/benchmarks | 1 | 基准 |
| **合计** | **476 文件 / 4,601 测试** | collect-only 实测 |

### 1.2 运行时长实测（按目录，WSL 环境）

| 目录 | 时长 | 判定 |
|------|------|------|
| l3/memory | **>270s（超时）** | 🔴 最大热点（r4_agent 系列） |
| l3/tool_system | 91.5s | 🔴 次热点 |
| l3/services | 47.5s | 🟠 中热点 |
| l4/lsp | 41.0s | 🟠 中热点（LSP stdio） |
| infra | 35.4s | 🟠 门禁文件反而慢 |
| l2 | 20.8s | 🟡 |
| l3/bus | 10.7s | 🟡 |
| l1 | 10.5s | 🟡 |
| l3/cell / agent / tools / l3a / card / boot / config / subagent / discussion / identity / error_bus / agent_terminal / session | 0.3–5.2s | 🟢 快 |
| l4/api_handlers / sandbox / api / adapters / auth / vault / search / rpc / mcp / llm_worker / llm / misc | 0.2–1.4s | 🟢 快 |
| integration | 3.2s | 🟢 |
| l5 / benchmarks | 0.3s | 🟢 |

注：`tests/l4/llm` 实测 `rc=5`（失败，游离于 runner 之外）；`tests/l3` 顶层单独跑因重复累加子目录而超时（非真实热点）。

### 1.3 Runner 覆盖率（核心问题）

| 维度 | 数值 |
|------|------|
| runner BATCH_1 + BATCH_2 条目 | 134（实际存在 133 文件） |
| 全库 test_*.py | 476 |
| **runner 覆盖率** | **27.9%** |
| 游离文件（不被 runner 管理） | **343**（l3=191, l4=81, l2=21, l1=20, infra=18, integration=9, l5=2, benchmarks=1） |

**结论**：双 batch 是「精选子集」而非全库切片。343 个文件只有全量 `pytest tests/` 才跑。

## 2. 切片方案

### 2.1 SLICES 定义（按层主键 + 慢热点副键）

| 切片 | 内容 | 预计时长 |
|------|------|---------|
| `infra` | 全部 22 个 infra 文件（门禁） | 35s（最先跑） |
| `l1` | 全部 33 个 l1 文件 | 10.5s |
| `l2` | 全部 23 个 l2 文件 | 20.8s |
| `l3-fast` | cell/agent/tools/card/bus/scheduler/l3a/boot/config/subagent/discussion/identity/error_bus/agent_terminal/session | ~35s |
| `l3-mid` | services(25) + tool_system(22) | ~139s |
| `l3-slow` | memory r4_agent 系列（原 BATCH_2 6 文件） | ~18s |
| `l3-memory-rest` | memory 其余 ~47 文件 | 需实测（若仍 >60s 再细分） |
| `l4-fast` | api_handlers/sandbox/api/adapters/auth/vault/search/rpc/mcp/llm_worker/llm/misc | ~7s |
| `l4-lsp` | lsp(2) | 41s（独立） |
| `l5` | 2 文件 | 0.3s |
| `integration` | 12 文件 | 3.2s |
| `benchmarks` | 1 文件 | 0.3s |

### 2.2 运行策略

| 模式 | 命令 | 行为 |
|------|------|------|
| 全量 | `python tests/runner.py` | 按依赖序跑全部 SLICES |
| 单切片 | `python tests/runner.py --slice l3-fast` | 失败定位 |
| 兼容 | `python tests/runner.py --batch 1\|2` | BATCH_1 = 除 l3-slow 外全部；BATCH_2 = l3-slow |
| 指定文件 | `python tests/runner.py <pattern>` | 保留 |
| 并行 CI | `python tests/runner.py --parallel` | 各 SLICES 以 `-n auto --dist loadfile` 并行，墙钟 82s→~35s |

### 2.3 CI 集成

- `test.yml` / `ci.yml`：单步 runner → `--parallel` 或 slice 矩阵 job（天然并行 + 失败隔离）
- `infra` 排第一：门禁违规立即失败（fail-fast）
- 343 游离文件按层归位 → runner 覆盖率 27.9% → **100%**
- `l4/llm` 失败项：纳入前先修复

### 2.4 向后兼容（零破坏）

- `--batch 1|2` / `<pattern>` / 默认双跑全部保留
- 仅新增 `--slice` / `--parallel` / `--list-slices`
- SLICES 从 BATCH_1/2 推导生成，现有调用零改动

### 2.5 与质量治理对齐

- 切片名与 `layer_quality.py` L1-L5 层一一对应 → 「质量扫描报 L3 违规 → `runner --slice l3-fast` 快速重跑」闭环
- CI 主流程：`quality-all`（结构+性能门禁）→ `runner --parallel`（测试回归）

## 3. 实施清单（待批准）

1. 改造 `tests/runner.py`：SLICES 表 + `--slice/--parallel/--list-slices` + 兼容层
2. 343 游离文件按层归位
3. 修 `l4/llm` 失败项（rc=5）
4. `l3/memory` 超时拆分（r4_agent 独立 + 其余子域化）
5. CI 更新（test.yml/ci.yml slice 矩阵）
6. 验证：全库回归 + 机器判定
