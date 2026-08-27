# Praxis 性能优化审查报告（2026-08-11）— 并发公平性修复 + 观察项记录

Date: 2026-08-11 · Scope: 主树性能审查（performance-analyzer 工作流）· 结论：1 个 P2 已修复 + 2 个 P3 观察项 · 修复分支：`feature/fix-rwlock-fairness`

## 1. P2 已修复 — RWLock 读者优先饥饿（`systems/python-reference-runtime/l1/kernel/sync.py`）

| 项 | 详情 | 状态 |
|---|---|---|
| 问题 | `RWLock.read_lock` 不检查 `_write_waiters`；持续读者流可饿死排队的写者直至 `RWLOCK_DEFAULT_TIMEOUT` | ✅ 本分支修复 |
| 影响面 | 工具执行热路径：`tool_pipeline.py` 每次工具执行按意图获取读写锁且**跨执行持有**；`cell_sandbox.py` 同型使用 | — |
| 修复 | 写者优先门控（`_write_waiters > 0` 时新读者等待）；同 agent 可重入读豁免（防死锁）；`_write_waiters` 计数移入锁内（消除无锁自增竞态）+ `try/finally` 兜底归零 | 本分支 |
| 测试 | 写者排队阻塞新读者 / 可重入读豁免 / 超时后 waiter 归零（`tests/l1/test_sync.py`） | ✅ |

## 2. P3 观察项（未修复，供后续工作参考）

### 2.1 MemoryManager 单一锁（`systems/python-reference-runtime/l3/memory/memory.py:53`）— 观察项保留

| 位置 | 发现 | 说明 |
|---|---|---|
| `self._lock = threading.Lock()` | 共享锁保护 persist/ingest mixin 写路径（`memory_persist.py`/`memory_ingest.py` 的 `with self._lock`）；ring 热路径由 `RingLayer` 各自持锁 | 曾误判为死锁并尝试移除，核验 mixin 后还原（`feature/fix-perf-p3`）。无实测竞争证据，观察项保留，规模化时按 ring/agent 细化 |

### 2.2 gatechain 单锁每次工具调用（`systems/python-reference-runtime/l1/kernel/gatechain.py:128,192`）

| 位置 | 发现 | 主流标准 | 预期收益 |
|---|---|---|---|
| `self._lock = threading.Lock()` | 每次工具执行检查门链加单锁 | 读优化（读锁/无锁路径） | 低（临界区已短；高吞吐时监控） |

## 3. 健康核验结论（无问题区域）

- **审计**：有界 deque（O(1) 裁剪）+ 线程本地批处理（`_AUDIT_FLUSH_SIZE` 才锁一次）+ O(k) 查询
- **syscall 派发**：预注册字典查找（无每次构建）
- **allocator**：每 agent 分片 RLock + O(1) 热路径；OOM 全局锁仅罕见路径（P1 修复完整）
- **进程表**：dict + 顺序 PID 计数器（O(1) 分配/查找）；僵尸后台回收按 `PROCESS_TABLE_MAX` 封顶
- **HTN**：单层分解无递归（无爆炸路径）；`route_subtask` 每 shard O(1)（微秒级）
- **LLM/I-O**：`http_pool.py` 连接池复用；`generate_with_cache` KV 缓存 + 按 agent 隔离；TTL/轮询合理（非激进）
