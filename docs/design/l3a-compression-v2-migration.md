# L3A 上下文压缩子系统 v2 迁移计划（3.1 补充缺口）

> 状态：Phase 0（计划落定）
> 分支：`feature/l3a-compression-migration`（worktree `/home/guiling/dev/praxis-compression`）
> 关联：`docs/architecture/l3-memory.md`、`docs/architecture/l3a-central.md`、`docs/architecture/perf-baseline.md`

## TaskStartSnapshot

- HEAD：`1a396e650f5cd5f21e9047c4a2e073ff55727bb8`（= `origin/main`）
- 基线：`tests/l3/l3a/test_compression_ratio.py`、`tests/l3/agent/{test_compression_guard,test_sensitive_detect,test_digest_cache,test_tool_result_cache}.py`、`tests/l3/config/test_cache_strategy.py` 共 27 tests 全绿（worktree src 经 `pyproject.toml [tool.pytest.ini_options] pythonpath=["src"]` 解析到 worktree）
- 迁移原则：绞杀者（strangler-fig）——老架构不动、新架构并行建、配置门控过渡态、验证后迁移、最后移除老路径

## 1. Goal

在不破坏现有行为的前提下，补齐 L3A 上下文压缩子系统"3.1 补充"的七个缺口，最终以新架构替换老架构：

1. **G3** 配置文件驱动持久化（digest/offload/sensitive/compression-guard 开关）
2. **G4** 断路器错误风暴检测（补齐 docstring 已声明、代码缺失的路径）
3. **G5** RC 数据分析闭环（compress/offload/digest 事件 → ReferenceChannel/RecordCenter）
4. **G6** 敏感检测动作语义（report / redact / block 三级）
5. **G1/G2** 插件装配工厂 + 双 API 协议自动选型（无状态拼接不写死 + 有状态按服务商选型）
6. **G7** 压缩比性能基准（实测数值入 `config/quality/perf-baseline.yaml`）

## 2. Architecture

### 2.1 现状（老架构）

| 层 | 落点 | 形态 |
|---|---|---|
| 执行层 | `agent_loop.py` `_truncate_trail`(B1) / `_fold_result`+`_wrap_handler`(B2) | 内联 |
| 决策层 | `session_compress.py` mixin（B3 ratio / B4 dedup / B5 五级管线 + 敏感扫描 + guard） | mixin |
| 守卫 | `agent/compression_guard.py`、`agent/sensitive_detect.py` | 模块级 `_state` 内存态 |
| 缓存 | `agent/digest_cache.py`、`agent/tool_result_cache.py` | 模块级 `_state` 内存态 |
| 前缀缓存 | `config/cache_strategy.py` | 已配置驱动（`praxis.yaml llm.cache`） |
| LLM | `l4/llm/llm_engine.py`（无状态 `generate`）、`l4/llm/llm_providers.py`（各 provider 硬编码拼接） | 硬编码 |

### 2.2 目标（新架构）

- 统一配置驱动：4 个开关经 `SettingsCenter`（`_L1_DEFAULTS` ← `praxis.yaml` ← `.praxis_settings.json` 持久化），运行时 API/L2 改动也落盘
- 插件装配工厂：provider 无状态消息拼接经 registry 装配（默认策略复刻现状，插件可注册覆盖）
- 显式协议选型：每 provider `protocol = stateless | stateful | auto`，`auto` 默认按 provider 能力 + 上下文形态选型
- 错误风暴检测：断路器 `check_recursion` 补上 error-storm 路径
- RC 闭环：`get_rc().event(...)` 记录压缩/卸载/摘要结构化事件
- 敏感语义：`report | redact | block`，默认 `report`（现状，不改弱安全姿态）
- 基准：压缩比基准入 `config/quality/perf-baseline.yaml`

## 3. Migration strategy（绞杀者迁移）

```
Phase 0  计划落定（本文档）
Phase 1  增量地基（无行为变化，新模块/新事件并行）
  1.1 G3 配置持久化    1.2 G4 错误风暴    1.3 G5 RC 闭环
Phase 2  新架构核心（装配工厂 + 协议选型 + 敏感语义）
  2.1 G1/G2 装配工厂 + 协议选型    2.2 G6 敏感动作语义
Phase 3  迁移切换（配置门控翻转 + dual-run parity 验证）
Phase 4  移除老路径（单独提交，仅在新路径 parity 通过后）
Phase 5  基准（G7 压缩比实测 + 基线落盘）
```

## 4. Baseline / Authority refs

- `docs/architecture/l3-memory.md`（Context isolation + 3.1 B1–B6 现状）
- `docs/architecture/l3a-central.md`（History compression 五级管线）
- `docs/architecture/perf-baseline.md`（`perf_quality.py` + `perf-baseline.yaml` 契约）
- `src/l1/kernel/params/system.py`（B1/B2/B6 默认常量）
- `config/discovery/commits.yaml`（提交门禁）

## 5. Compatibility boundary（兼容边界）

- 默认开关**不变**：digest off / offload on / sensitive on / recursion 0(off) / breaker on
- 老路径在 Phase 3 验证前**不动**；新路径经配置门控引入，默认走老行为
- API（`/api/v2/memory/{digest,tool-result,sensitive,compression-guard}`）与 L2（`/memory *`）开关面**不变**
- 导入方向不变（L3→L2→L1，测试 `test_layer_imports.py` 守护）

## 6. TDD route

- Mode：off；Decision：skipped
- Test posture：每切片 post-change regression（不写 RED 先行；本任务无显式 strict TDD 授权）
- Verification：`pytest -n 0 <target>` + `python tests/runner.py --batch 1`

## 7. Phases & Tasks（file map + verification）

### Phase 1.1 — G3 配置驱动持久化
- 改：`agent/digest_cache.py`、`agent/tool_result_cache.py`、`agent/sensitive_detect.py`、`agent/compression_guard.py` 的 `_state` 初始化从 `SettingsCenter.get(...)` 读初值；`set_*_switches` 写回 `SettingsCenter.set(...)`（落盘）
- 加：`settings_center.py` `_L1_DEFAULTS` 增 4 组键（值 = 现有 params 默认，不改行为）
- 测：`tests/l3/agent/test_{digest_cache,tool_result_cache,sensitive_detect,compression_guard}.py` + 新增持久化断言

### Phase 1.2 — G4 错误风暴检测
- 改：`agent/compression_guard.py` `check_recursion` 增 error-storm 计数（近窗口内连续压缩异常 → `_trip`）
- 改：`session_compress.py` 压缩异常路径上报 storm 信号
- 测：`tests/l3/agent/test_compression_guard.py` + 新增 storm 用例

### Phase 1.3 — G5 RC 闭环
- 改：`session_compress.py`、`agent_loop.py`、`digest_cache.py`、`tool_result_cache.py` 在压缩/折叠/卸载处 `get_rc().event("l3a_compress", {...})`
- 测：`tests/l3/l3a/test_compression_ratio.py` + 断言事件落 ReferenceChannel

### Phase 2.1 — G1/G2 装配工厂 + 协议选型
- 加：`l4/llm/assembly.py`（provider 无状态消息装配策略 registry，默认策略复刻 `llm_providers.py` 现状）
- 改：`l4/llm/llm_engine.py` `_get_strategy` → `get_strategy + get_protocol(provider)`；`tool_use`/有状态路径按 `protocol` 分流
- 测：`tests/l4/llm/*` + `tests/l3/config/test_cache_strategy.py`

### Phase 2.2 — G6 敏感动作语义
- 改：`agent/sensitive_detect.py` 增 `action = report|redact|block` 开关（默认 report）；`session_compress.py`/`agent_loop.py` 按 action 处理命中
- 测：`tests/l3/agent/test_sensitive_detect.py` + 新增 redact/block 用例

### Phase 3 — 迁移切换
- 配置门控翻转 + dual-run parity 对比（新旧路径同输入比对输出/压缩比/敏感命中）
- 测：全量 `python tests/runner.py --batch 1` + `bash scripts/sh/verify-completion.sh`

### Phase 4 — 移除老路径
- 删：`agent_loop.py` 内联 B1/B2 分支、`session_compress.py` 旧 mixin 分支（仅在新路径 parity 后，单独提交）
- 测：全量回归 + `verify-completion.sh` COMPLETE

### Phase 5 — G7 压缩比基准
- 加：`tests/benchmarks/bench_compression.py`（真实会话/工具结果规模压缩比采样）
- 改：`config/quality/perf-baseline.yaml`（`perf_quality.py --baseline` 生成，不手改）
- 测：`python tests/benchmarks/bench_compression.py --json` + `python scripts/py/perf_quality.py --baseline`

## 8. Open decisions（已定默认值，均可反悔）

- **D1 G6 敏感语义**：默认 `report`（现状）；新增 `redact`/`block` 经 config 门控，不改变安全姿态
- **D2 G2 协议选型**：`protocol=auto` 默认，按 provider 能力探测 + 上下文形态（单轮→无状态，多轮→有状态）
- **D3 G1 装配工厂**：扩展 `cache_strategy.register_strategy` 为装配策略（消息拼接 + 协议），默认策略复刻现状硬编码行为
- **D4 移除边界**：Phase 4 单独提交，仅在新路径 parity 验证通过后；移除范围限定 B1/B2 内联分支

## 9. Risks & retirement

- **风险**：迁移期新旧双写导致观测翻倍（G5）→ 事件带 `v2` 标记区分；协议选型误判（D2）→ `auto` 兜底回退当前 `generate`
- **回滚面**：每 Phase 独立提交，配置门控一键回退到老行为
- **退休**：老路径移除后 `docs/architecture/l3-memory.md` / `l3a-central.md` 同步更新（同提交）
