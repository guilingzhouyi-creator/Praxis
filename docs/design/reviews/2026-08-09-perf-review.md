# Praxis 性能优化审查报告（2026-08-09）— 双模式文件

Date: 2026-08-09 · Scope: 双模式切换文件（**不在拆分改造范围内**，仅性能优化审查）· Companion: `2026-08-09-decouple-review.md`
原则：不迁移架构、不改结构；热路径优化落地 + 剩余项对照主流标准量化。

## 0. 已确认的双模式文件清单

`l3.py`（L3A/L3B）、`api_routes.py`（v1/v2，v1 已移除）、`subagent.py`（同步）/`scout.py`（异步）、`subagent_pool.py`（双缓冲）、`cache.py`（双委派模式）、`tool_mode.py`（读写）、`security_mode.py`（productive/security-test）、`memory_graph.py`（hybrid/paused）、`mcp_bridge.py`（import/export）、`_subagent.py`（review/deploy/scout）、`harness.py`（门控矩阵）、`skill_retriever.py`（tfidf/embedding）、`models.py`↔`card_unified.py`（新旧 Card）。

## 1. 第一轮已落地的性能优化（未动结构）

| 文件 | 优化内容 | 状态 |
|---|---|---|
| `l3/memory/cache.py` | `get()` 内单次 `now`（原每次访问经 `expired` 属性再调时钟）；`CacheEntry` 构造合并为一次时钟调用（原两次） | ✅ 已提交 |
| `l3/tool_system/tool_mode.py` | `_save_mode` 文件 I/O + `_apply_mode` 移出 `_MODE_LOCK`（不再锁内落盘） | ✅ 已提交 |
| `l3/agent/subagent_pool.py` | 清理循环：快照锁内 → 过期计算锁外 → 删除锁内，缩短持锁 | ✅ 已提交 |
| `l3/memory/memory_graph.py` | `_pick_pairs` 去重由 list 包含 O(n²) → set 查重 O(n) | ✅ 已提交 |

## 2. 剩余热点与主流标准对照

### 2.1 `l3/memory/cache.py`

| 位置 | 发现 | 主流标准 | 预期收益 |
|---|---|---|---|
| `invalidate()`/`invalidate_by_tag()` | O(n) 全表扫描，且每条目每次重建 `set(e.tags or set())`（分配重） | Redis tag→key **倒排索引**，按 tag O(m) 删除 | O(n·k) → O(m) 失效；消除每条目 set 重建 |
| `ContextRegister.store()` | 双 `time.time()` 存 timestamp+expires_at（与已修 CacheEntry 同型） | 单次时钟读 | 微 CPU + 一致性 |
| `get()` 命中路径 | 锁内 per-agent 计数更新；RLock + OrderedDict O(1) 可接受 | 热计数器 GIL 下可无锁/批量 | 小（保留） |

### 2.2 `l3/agent/subagent_pool.py`

| 位置 | 发现 | 主流标准 | 预期收益 |
|---|---|---|---|
| `collect()`/`collect_all()` | **busy-poll**：`time.sleep(POLL_INTERVAL_DEFAULT=0.1s)` 循环 → 每次 collect 最多 +100ms 延迟 | `threading.Event`/`Condition` 每任务等待，或 `Future.result()` | 0–100ms 延迟削减；减少唤醒 |
| `commission()` | `task_id` 基于锁外读的 `_total_commissioned`（并发可重复）→ 锁内自增 | 锁内原子计数（先读后增同锁） | 正确性 + 无重复 id |
| 清理循环 | 已快照优化（第一轮）✅ | — | 已完成 |

### 2.3 `l3/memory/memory_graph.py`

| 位置 | 发现 | 主流标准 | 预期收益 |
|---|---|---|---|
| `extract_semantic_edges` | **逐对串行 LLM 调用**（每对 1–5s，N× 延迟） | 独立 pair 并发（`concurrent.futures`，LLM 为 I/O 型）；保留自动降级 `paused` | N → N/workers（如 8 对 4 worker ≈ 2×） |
| `_pick_pairs` | set 去重 ✅（第一轮） | — | 已完成 |
| `_ask_relation` | 每对重建 prompt；可接受 | — | 保留 |

### 2.4 `l3/tool_system/tool_mode.py`

| 位置 | 发现 | 主流标准 | 预期收益 |
|---|---|---|---|
| `_save_mode()` | 每次切换全量 JSON + `os.replace`，已移出锁 ✅ | 低频可接受；若 API 高频调用可 debounce | 已完成；可选 debounce（P3） |
| `get_mode()` | 无锁全局读 ✅ | GIL 原子 str 读 | 保留 |

## 3. 其余双模式文件

### 3.1 `l3/memory/skill_retriever.py` — **最高价值**

`TfIdfSkillRetriever.rank()` 每次调用**重算全部候选的 token 向量**（`_tokens(text)` → `Counter`），而 `AgentLoop` 每轮调用 `retrieve_skills`。

| 发现 | 主流标准 | 预期收益 |
|---|---|---|
| 候选向量 + IDF 每次调用重算 | sklearn `TfidfVectorizer`/Lucene 预计算文档向量并缓存（按 skill revision 失效），仅查询侧分词 | O(候选×文本长) → O(查询长 + 查表)；AgentLoop 注入主导 CPU 削减 |
| 无停用词/词干（仅 `len(w)>2`） | 标准 TF-IDF 预处理 | 向量更小、噪声更少 |

### 3.2 `l3/tool_system/harness.py` + `security_mode.py`

| 发现 | 主流标准 | 预期收益 |
|---|---|---|
| `get_harness_mode()` 每次 pipeline 执行都查 `get_tool_config("harness_mode", …)`（docstring 自述） | 缓存静态配置值；`set_harness_mode()`/配置重载时失效 | 每次执行查配置 → 均摊 O(1) |
| `get_posture()` 每次重建 dict（gatechain/constitution 热路径读取） | 模式变更时 memoize | 小 |

### 3.3 `l4/mcp_bridge.py`

`_persist()` 锁内建状态 + 锁外全量 JSON dump（低频生命周期操作）→ 保留；17 处锁多为短读 → 保留。若未来高频化再加 debounce。

### 3.4 `l3/cell/peers/l3.py`（L3A/L3B 路由）

`_rule_parse`：`text.lower()` 在循环内对每个路由关键字重复计算 → **提升到循环外**（O(routes) 冗余 lower → 1）；`_routes` 字典小，保留。

## 4. 全局热点（非双模式，同审查标准）

| 文件 | 发现 | 主流标准 | 预期收益 |
|---|---|---|---|
| `l1/kernel/skill_retrieval.py`（query/rules_for） | 每查询重分词 + 全量扫描；`rules_for` 每条目 `name.lower()` | 倒排索引；预计算小写名 | O(skills×terms×rules) → O(terms) |
| `l1/kernel/constitution.py`（check） | 每次动作遍历全部 17+ 规则并 `rule.evaluate` | 按 action/tag 预索引，仅评估相关子集 | 17 → 2–5 次/动作；减少 `_trigger_violation`/`_describe` 字符串构建 |
| `l1/kernel/sync.py`（Mutex.acquire） | 等待循环每迭代 3–4 次 `time.time()` | 每次迭代取一次 `now`；`_cond.wait(timeout=remaining)` 已正确 | 微 CPU（正确性无碍） |
| `l3/agent/agent_loop_run.py` | 每步 `str(tc)[:LOG_TRUNC_200]` + `sum(len(str(tc))…)` 对全部历史结果重字符串化 → O(n²) | 运行总量维护；即时截断 | O(n²) → O(n)（长循环，n ≤ 999999 哨兵） |
| `l3/tool_system/tool_pipeline.py` | 9 步管道 + 每步计时；相对工具执行开销可忽略 | 保留 | — |
| `l3/memory/memory.py` | `_ring(n)`/`_ttl_for(n)` 字典查找 O(1) | 保留 | — |
| `l3/boot/boot_steps/*` | 启动期 lazy import 保持模块化；无运行时热路径 | 保留 | — |

## 5. 主流标准对照汇总

| 标准 | 现状 | 建议 |
|---|---|---|
| 锁粒度 / 无锁读 | 热缓存 RLock；mode/posture 全局无锁读 ✅ | 保留；仅 `subagent_pool` 计数器需原子化 |
| 缓存命中 + 失效 | LRU `move_to_end` O(1) ✅；tag 失效 O(n) + 每条目 set 重建 | 倒排索引 |
| TF-IDF / 向量排序 | 每查询重算候选向量 | 预计算候选向量 + IDF，按 revision 缓存 |
| IO | `os.replace` 原子写 ✅；persist 已移出锁 ✅ | 仅频率升高时 debounce |
| GC / 分配 | 热路径每条目 `set()`/`Counter`/`str()` 重建 | 提升/复用；运行总量 |
| 日志 | lazy `%s` ✅ | 保留；热路径避免 eager `str()` |

## 6. 优先级矩阵（未落地项）

| # | 项 | 文件 | 优先级 | 工作量 | 预期收益 |
|---|---|---|---|---|---|
| P1-1 | 预计算候选 token 向量 + IDF；仅查询侧分词 | `skill_retriever.py` | **P0** | M | AgentLoop 注入主导 CPU 削减 |
| P1-2 | 语义边 LLM pair 并发 | `memory_graph.py` | P0 | S | ~2× 墙钟（hybrid 提取） |
| P1-3 | Event/`Future` 等待替代 100ms 轮询 | `subagent_pool.py` | P0 | S | 每次 collect 0–100ms 削减 |
| P1-4 | `_total_commissioned` 原子化（正确性） | `subagent_pool.py` | P0 | S | 无重复 task id |
| P2-1 | tag→key 倒排索引失效 | `cache.py` | P1 | M | O(n·k) → O(m) |
| P2-2 | action 标签规则预过滤 | `constitution.py` | P1 | M | 17 → 2–5 次/动作 |
| P2-3 | 提升 `text.lower()`；运行总量 | `l3.py`/`agent_loop_run.py` | P1 | S | O(routes)/O(n²)→O(n) |
| P2-4 | harness 配置缓存 + set 失效 | `harness.py` | P1 | S | 每次执行查配置 → O(1) |
| P3-1 | `ContextRegister.store` 单时钟 | `cache.py` | P2 | S | 微 |
| P3-2 | skill 倒排索引（query/rules_for） | `skill_retrieval.py` | P2 | L | 每查询 O(n) → O(terms) |
| P3-3 | `_save_mode`/`_persist` debounce（频率升高时） | `tool_mode.py`/`mcp_bridge.py` | P2 | S | 可选 |

P0 = 每 agent 轮热路径 / 明确延迟；P1 = 每调用有意义成本；P2 = 微优化或条件性。

## 7. 验证门槛

- 双模式文件优化均为**行为等价**改动：相关域测试全绿（cache/tool_mode/memory_graph/subagent_pool 定向集）
- ruff 全树 + format 全绿

## 8. 实时核验证据（2026-08-09 复扫，`feature/decouple-split@a0d8138`）

### 8.1 已落地优化代码行证据

| 文件 | 优化 | 代码行证据 |
|---|---|---|
| `l3/memory/cache.py` | 单次时钟 | L34 `now = time.time()`（构造）、L94（get）、L102 `if now > entry.expires_at:` |
| `l3/tool_system/tool_mode.py` | 锁外 IO | L92 `_MODE = mode` 后 L93 注释 "Apply and persist OUTSIDE the lock" |
| `l3/agent/subagent_pool.py` | 清理快照 | L93 `items = list(self._session_history.items())` → L94 锁外计算过期 |
| `l3/memory/memory_graph.py` | set 去重 | L555 `seen: set[tuple[str, str]] = set()`、L568 `key not in seen` |

### 8.2 剩余热点实时定位（未落地）

| 热点 | 位置证据 |
|---|---|
| `subagent_pool.collect` 0.1s 轮询 | L181 / L208 `time.sleep(POLL_INTERVAL_DEFAULT)`（P0-3） |
| `skill_retriever` 候选向量每查询重算 | L56 `for cand in candidates:` → L58 `s_tok = self._tokens(text)`（P0-1） |
| `memory_graph` 语义边串行 LLM | `extract_semantic_edges` 逐对 `_ask_relation`（P0-2） |

P0-P3 优先级矩阵见 §6；均已记录待落地，未动结构。
