# Praxis 分层解耦审查报告（2026-08-09）

审查范围：`src/` 全树（约 99,206 行 Python3），以最新主干 `76a9184` 为基线。
原则：拆分为分层解耦；**禁止新增反向依赖**；**不迁移到新架构**；支持双模式切换的文件不改造，仅做性能优化审查（见 `2026-08-09-perf-review.md`）。

## 1. 大文件清单（>500 行，28 个）

| 行数 | 文件 | 处置状态 |
|---|---|---|
| 1313 | `l1/kernel/skill.py` | ✅ 已拆（`skill_policy`/`skill_guidance`/`skill_persist`/`skill_retrieval` mixin，核心 488 行） |
| 1055 | `l1/kernel/params/system.py` | 常量池，内聚良好，保留 |
| 886 | `l4/api/api_endpoints.py` | 端点清单（数据表），低优先级 |
| 882 | `l4/llm/llm.py` | ✅ 已拆（`LLMToolsMixin`→`llm_tools.py`、`LLMRetryMixin`→`llm_retry.py`，剩 714 行） |
| 875 | `l4/api/api_routes.py` | 路由表，低优先级 |
| 861 | `l1/kernel/constitution.py` | ✅ 已拆（`constitution_checks`/`constitution_io`，引擎 373 行） |
| 842 | `l3/boot/boot_steps.py` | ✅ 已拆（`boot_steps/` 包 9 个域模块） |
| 775 | `l3/error_bus/__init__.py` | ✅ 已拆（实现下沉 `core.py`，__init__ 瘦身为 43 行 re-export） |
| 751 | `l4/ci_review.py` | 评审逻辑，中优先级 |
| 718 | `l1/kernel/params/agent.py` | 常量池，保留 |
| 715 | `l3/card/card_unified.py` | 新旧 Card 桥，中优先级 |
| 687 | `l3/services/file_editor.py` | 工具实现，中优先级 |
| 675 | `l3/memory/memory_graph.py` | 双模式文件（hybrid/paused），不改造，仅性能审查 |
| 652 | `l4/search/search_engine.py` | 检索引擎，中优先级 |
| 651 | `l4/mcp_bridge.py` | 双模式文件（import/export），不改造 |
| 626 | `l3/bus/htn_planner.py` | 规划器，中优先级 |
| 623 | `l3/agent/agent_loop_run.py` | 主循环，中优先级 |
| 611 | `l4/llm/llm_providers.py` | Provider 实现，中优先级 |
| 592 | `l4/api_handlers/__init__.py` | ✅ 评估保留（纯委托门面：440 行类体全部 `return xxx(body)` 一行转发，业务逻辑已在 21 个 `api_handlers_*.py` 域模块内；拆 mixin 只平移方法不降耦合） |
| 576 | `l1/kernel/gatechain.py` | 门链，中优先级 |
| 566 | `l1/kernel/ports.py` | 12 个 Port ABC，可拆 ports/ 包 |
| 556 | `l3/cell/peers/l3a/__init__.py` | 大 __init__，待后续下沉 |
| 553 | `l4/sandbox/cell_sandbox.py` | 沙箱，中优先级 |
| 550 | `l3/services/user_profile.py` | 服务，中优先级 |
| 548 | `l3/tool_system/tool_pipeline.py` | 9 步管道，中优先级 |
| 521 | `l3/agent_terminal/__init__.py` | 大 __init__，待后续下沉 |
| 506 | `l1/kernel/sync.py` | 锁原语，内聚良好，保留 |
| 501 | `l3/services/prompt_engine.py` | 提示引擎，低优先级 |

拆分全部在同层内进行（复用既有 mixin 提取 + 包化惯例），不新增跨层导入、不迁移架构。

## 2. 过耦合文件与反向依赖

### 反向依赖（红线）

| 位置 | 问题 | 处置状态 |
|---|---|---|
| `l1/kernel/settings.py` → `l3.config.settings_adapter` | 全树唯一 L1→L3 向上依赖（白名单豁免），thin proxy + lazy import 规避循环 | ✅ **已依赖倒置**：新增 `set_settings_provider()` 注入点（boot 时由 `boot_steps/config.py` 装配），未注入时用 DEFAULTS 回退；conftest 重置后模拟 boot wiring 重新注入；白名单条目已移除 |

### 跨层 import 枢纽（按白名单命中数）

| 文件 | 跨层 import 数 | 处置状态 |
|---|---|---|
| `l2/l2_shell/commands/extra.py` | 11 条白名单（L2→L3 ×9、L2→L4 ×2） | ✅ **已按域拆 5 个子模块**：`extra_cluster`/`extra_mcp`/`extra_security`/`extra_resources`/`extra_stats`；`extra.py` 变薄门面（35 行）保持导入兼容；白名单条目改指新文件 |
| `l3/boot/wiring.py` | 12 | ✅ 保留（合法集中装配点）；worker/channel 适配器已改指 L1，白名单减 2 条 |
| `l2/l2_shell/commands/memory.py` | 11 | ⏳ 收敛 L3 门面 |
| `l2/l2_shell/commands/model.py` | 11 | ⏳ 收敛 model 门面 |
| `l2/l2_shell/commands/system.py` | 8 | ⏳ 收敛系统门面 |
| `l3/config/config_handlers_bridge.py` | 7（L3→L4） | ⏳ 改走 port 访问 |
| `l2/selector.py` / `l2/shell.py` | 6 / 5 | ✅ 可接受（命令分发） |
| `l3/services/adapter_bridge.py` | 4 | ✅ 已是门面，保留 |
| `l2/i18n.py` → `l4.adapters.i18n_yaml` | L2→L4 跳层 | ✅ 白名单内适配器模式，可接受 |

### 循环导入规避（既往拆分半成品，~17 处 lazy import）

| 集群 | 现状 | 处置状态 |
|---|---|---|
| l3a session mixins（session_ask/persist/prompt/compress）lazy import `session.py` | 共享类型未下沉 | ✅ 已改指叶子模块 `session_history.py`，循环债消除 |
| card mixins（card_convention/card_execution_stats）lazy import `card_registry.py` | `CardLifecycle` 未下沉 | ⏳ 类型下沉 `card_models.py` |
| memory mixins（memory_persist）lazy import `memory.py` | `MemEntry` 未下沉 | ⏳ 类型下沉 `memory_models.py` |
| agent_terminal mixins（worker_pool/card_execution）lazy import 父 `__init__` | 类型未下沉 | ⏳ 下沉独立模块 |
| `constitution.py`/`skill.py`/`scout.py` 同层 lazy import | 同层循环 | ✅ 已在拆分中消除 |

## 3. 兼容层遗留文件（逐个处置）

| 文件 | 性质 | 处置状态 |
|---|---|---|
| `l4/adapters/worker_thread.py`、`channel_ring.py` | 纯 re-export shim（实现已迁 L1） | ✅ **已删除**：wiring/adapters/tests 改指 `l1.kernel.*`，白名单 2 条移除 |
| `l3/agent/subagent_framework.py`、`subagent_dispatcher.py` | 类级架构 DEPRECATED（SubAgentPool 取代），但 **API handler 仍活跃**：`/api/v2/subagent/*` 7 条路由 + ENDPOINT_MANIFEST 直接引用 `handle_*`，api_gateway 注册、24 处测试覆盖，无替代实现 | ✅ 保留（活跃 API 后端；删除会破坏 API 合约，违反版本化/不迁移原则） |
| `l3/card/models.py` | 旧 Card 桥（仅剩 `to_old_card()` 使用） | ⏳ 属双模式共存，保持桥但 `to_old_card` 拆独立文件 |
| `l4/llm/llm_base.py` | `ToolDef` deprecated + `LLMConfig` re-export | ✅ 保留（均有活跃消费者：llm 回退逻辑、`_term_lifecycle`、测试构造） |
| `l1/kernel/settings.py` | thin proxy（连带 §2 反向依赖） | ✅ **已依赖倒置**（见 §2） |
| `l3/memory/memory_quality.py` | `_MIN_CONTENT_LEN` re-export alias | ✅ **已删除**（测试改指 `MEMORY_MIN_CONTENT_LEN`） |
| `l5/agent_runtime.py` | `_release_all` 空 stub | ✅ **已删除**（无调用者） |
| `l4/ci_review.py` | `CI_SETTING_KEYS` back-compat alias | ✅ 保留（仍被派生使用，无害） |
| `l3/config/settings_center.py` | `session.max_turns` deprecated → `l3a.max_turns` | ✅ **已删除**（消费点改 `l3a.max_turns`，修复重复 key） |
| `l3/tool_system/tool_spec.py` | auto-discovery deprecated → ToolConfig.load | ✅ **已删除 `auto_discover`**（无调用者）；ToolConfig 保留 |

## 4. 双模式文件（不改造）— 性能优化审查

已确认的双模式文件：`l3.py`（L3A/L3B）、`api_routes.py`（v1/v2，v1 已移除）、`subagent.py`（同步）/`scout.py`（异步）、`subagent_pool.py`（双缓冲）、`cache.py`（双委派模式）、`tool_mode.py`（读写）、`security_mode.py`（productive/security-test）、`memory_graph.py`（hybrid/paused）、`mcp_bridge.py`（import/export）、`_subagent.py`（review/deploy/scout）、`harness.py`（门控矩阵）、`skill_retriever.py`（tfidf/embedding）、`models.py`↔`card_unified.py`（新旧 Card）。

这些文件**不在拆分范围内**，仅做性能优化审查。第一轮已落地的性能优化（在拆分过程中附带完成，未动结构）：

1. **`l3/memory/cache.py`（热路径）** ✅：`get()` 内单次 `now`（原每次经 `expired` 属性再调时钟）；`CacheEntry` 构造合并为一次时钟调用。剩余：`invalidate` O(n) 扫描 + 每条目重建 set（P1-1）。
2. **`l3/tool_system/tool_mode.py`** ✅：`_save_mode` 文件 I/O + `_apply_mode` 移出 `_MODE_LOCK`（不再锁内落盘）。剩余：可选 debounce（P3）。
3. **`l3/agent/subagent_pool.py`** ✅：清理循环快照锁内、过期计算锁外、删除锁内，缩短持锁。剩余：`collect` 0.1s 轮询空转（P0-3）、`_total_commissioned` 锁外读竞态（P0-4）。
4. **`l3/memory/memory_graph.py`** ✅：`_pick_pairs` 去重由 list O(n²) 改 set O(n)。剩余：语义边提取逐对串行 LLM 调用（P0-2）。

完整性能审查（含其余双模式文件 `skill_retriever`/`harness`/`security_mode`/`mcp_bridge`/`l3.py` 与全局热点、主流标准对照、11 项优先级矩阵）见 `2026-08-09-perf-review.md`。

## 5. 执行状态

- ✅ 已完成：skill/constitution/boot_steps/error_bus/llm/extra 六大文件拆分；l3a session 循环债消除；L1→L3 反向依赖倒置；worker_thread/channel_ring shim 删除；memory_quality alias、agent_runtime stub、session.max_turns、auto_discover 清理；layer_imports 白名单同步；双模式文件第一轮性能优化；测试对齐（含 extra 子模块覆盖补齐 + `_cmd_think` 死调用修复）
- ⏳ 待办（后续批次）：L2 memory/model/system 命令扇出收敛、card/memory/agent_terminal 类型下沉、剩余大 __init__ 下沉（l3a/api_handlers 已评估为门面保留）、双模式性能 P0/P1 项落地

## 6. 验证门槛（全部通过）

- `pytest tests/infra/test_layer_imports.py -x -q`（新模块零跨层违规）✅
- `pytest tests/infra/test_params_compliance.py -x -q`（params 常量合规）✅
- 域测试 + ruff 全树全绿 ✅

## 7. 实时核验证据（2026-08-09 复扫，`feature/decouple-split@a0d8138`）

### 7.1 大文件拆分前后行数对比（基线 76a9184 → 当前）

| 文件 | 基线 | 当前 | 缩减 |
|---|---|---|---|
| `l1/kernel/skill.py` | 1313 | 487 | **−826** |
| `l1/kernel/constitution.py` | 861 | 380 | **−481** |
| `l3/error_bus/__init__.py` | 775 | 43 | **−732** |
| `l4/llm/llm.py` | 882 | 702 | **−180** |
| `l3/boot/boot_steps.py` | 842 | 0（拆为 9 域模块包，合计 992 行） | **−842** |
| `l2/l2_shell/commands/extra.py` | 225 | 35（5 域子模块合计 314 行） | **−190** |

### 7.2 过耦合/反向依赖实时核验

| 检查 | 实时结果 |
|---|---|
| `l1/kernel/settings.py` 反向依赖 | **0 条白名单命中**（依赖倒置完成，白名单条目已移除） |
| `extra.py`（原 11 条白名单） | **0 条**（拆为 extra_cluster 3 / extra_mcp 4 / extra_resources 2 / extra_security 1 / extra_stats 8） |
| `l3/boot/wiring.py` | 12 → **8**（worker/channel 适配器改指 L1 后白名单减 2） |
| 当前白名单总数 | 89 条（基线 92 条 − settings 1 − wiring 2） |

### 7.3 兼容层实时核验

| 检查 | 实时结果 |
|---|---|
| `worker_thread.py` / `channel_ring.py` shim | **已删除**（git log `a2a28d0` 确认 D 记录） |
| `auto_discover` / `session.max_turns` / `_release_all` / `_MIN_CONTENT_LEN` 残留 | **无函数残留**（仅 params 常量 `MEMORY_MIN_CONTENT_LEN` 与 `tool_config.py` docstring 提及） |
| `ToolDef` 保留核验 | tests/l4/test_llm.py 4 处引用（活跃消费） |
| `subagent_framework` 保留核验 | api_routes 7 处 + api_endpoints 15 处引用（活跃 API 后端） |
