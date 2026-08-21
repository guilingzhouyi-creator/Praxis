# Praxis 测试代码注释完整性审计 & TypeScript 重写参考资料

> 生成目的：为后续使用 TypeScript 重写 Praxis 测试代码的其他 Agent 提供完整的注释规范、模式映射和迁移参考。
>
> 审计时间：基于当前 `tests/` 目录 (598 个 .py 文件, 29,171 行)
> 目标：注释完整性基线 + TS 可翻译参考

---

## 一、注释完整性审计总览

| 指标 | 数值 | 评价 |
|------|------|------|
| 测试文件总数 | 598 | — |
| 无模块 docstring 文件数 | 36 | 绝大多数为 `__init__.py`，可接受 |
| 无类 docstring 的类数 | 566 | ⚠️ 严重不足 |
| 测试方法总数 | 4,803 | — |
| 无方法 docstring 的方法数 | 3,558 | ⚠️ 仅 25.9% 有注释 |
| 注释覆盖率（方法级） | 25.9% | 远低于 AGENTS.md 要求的"public function docstring required" |

### 最严重的 5 个文件（方法注释缺失率 100% 或接近 100%）

| 文件 | 缺失/总计 | 缺失率 |
|------|-----------|--------|
| `tests/l4/test_ci_review.py` | 77/77 | 100% |
| `tests/l1/test_kernel.py` | 44/45 | 98% |
| `tests/l1/test_kernel_allocator.py` | 43/44 | 98% |
| `tests/l1/test_kernel_tool_chain.py` | 40/46 | 87% |
| `tests/integration/test_skill_progressive_integration.py` | 38/38 | 100% |

### 注释良好的文件（可作为 TS 重写模板）

| 文件 | 特点 |
|------|------|
| `tests/conftest.py` | 模块 docstring + 每个 fixture docstring + 段落注释 |
| `tests/l2/test_l2_shell_e2e.py` | 完整 docstring 体系 + 段落分隔 |
| `tests/l3/cell/test_interrupt.py` | class docstring + method docstring + 段落注释 |
| `tests/runner.py` | 模块 docstring + 每个函数 docstring |
| `tests/l1/test_kernel_resource.py` | class docstring + 部分 method docstring |

---

## 二、Praxis 测试代码注释规范

### 2.1 模块级 docstring（每个测试文件必须）

```python
"""L1 Kernel — core module importability and API tests."""
```
- **格式**：`"""` 双三引号
- **内容**：被测模块 + 测试范围描述，一句英文
- **英文优先**：AGENTS.md 明确要求 "English baseline for all comments/docstrings"

### 2.2 段落分隔注释

```python
# ═══════════════════════════════════════════════════════════════════
# TerritoryConstitution
# ═══════════════════════════════════════════════════════════════════
```

或更简洁的：

```python
# ── Fixtures ──
# ── Built-in IRQ tests ──
# ── Trigger tests ──
```

- `═══` 用于大的功能分区（对应源代码中的 class/section）
- `───` 用于小的逻辑分组（fixtures、子功能组）

### 2.3 类 docstring

```python
class TestResourceLimiterConstruction:
    """Construction and singleton access."""

    def test_limiter_created(self): ...
```

- 格式：class 定义后紧跟 `"""短句."""`
- 内容：描述该类测试的**职责边界**，不重复类名
- **注意**：当前 566 个类缺少此注释，TS 重写时应补全

### 2.4 方法级 docstring

```python
    def test_trigger_nmi_inline(self, irq):
        """NMI fires handler immediately."""
```

- 格式：方法签名后紧跟 `"""一句话说明."""`
- **关键**：说明**测试意图**而非断言本身
- 好例子：`"NMI fires handler immediately."`
- 差例子（无注释）：直接写断言代码

### 2.5 行内注释

```python
# May be rejected by preconnect due to LLM/provider unavailability, but routing itself is correct
assert isinstance(r, dict)

# summary() returns a human-readable string (LLM context), not a dict
assert isinstance(s, str)
```

- 用于解释**为什么**这样断言，或者**特殊边界条件**
- 不用来解释显而易见的代码

### 2.6 英文 vs 中文

```python
# 正确 ✅ — 英文
# May be rejected by preconnect due to LLM/provider unavailability

# 禁止 ❌ — 中文
# 可能会因为LLM不可用被拒绝
```

- AGENTS.md：`English baseline for all comments/docstrings — CJK only in intentional data (i8n, injection keywords)`

---

## 三、Praxis 测试代码模式（TS 重写映射）

### 3.1 `sys.path` 注入模式（94 个文件使用）

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
```

**TS 等价物**：
- 若使用 ts-node + tsconfig path mapping：
  ```json
  // tsconfig.json
  {
    "compilerOptions": {
      "paths": {
        "l1/*": ["src/l1/*"],
        "l2/*": ["src/l2/*"],
        "l3/*": ["src/l3/*"],
        "l4/*": ["src/l4/*"],
        "l5/*": ["src/l5/*"]
      },
      "baseUrl": "."
    }
  }
  ```
- 若使用 Jest/vitest：配置 `moduleNameMapper` 或 `alias`
- **注意**：TS 重写后应移除所有 `sys.path.insert`，由构建工具处理路径解析

### 3.2 单例 reset 模式（核心基础设施）

```python
# conftest.py 中的 autouse fixture
@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset known singletons before each test to prevent state pollution."""
    for module_name, (func_name, _) in _RESETS.items():
        if module_name not in sys.modules:
            continue  # never imported → no singleton to reset
        mod = sys.modules[module_name]
        fn = getattr(mod, func_name, None)
        if fn:
            fn()
```

**TS 等价物**：
```typescript
// setup.ts (vitest/jest global setup)
beforeEach(() => {
  for (const [modName, resetFn] of RESET_MAP) {
    const mod = globalThis.__loadedModules?.[modName];
    if (mod && mod[resetFn]) {
      mod[resetFn]();
    }
  }
});
```

**关键 `_RESETS` 映射表**（TS 重写时需要完整迁移）：
```python
_RESETS = {
    "l4.api.api_gateway": ("stop_api", None),
    "l4.ci_review": ("reset_service", None),
    "l1.kernel.capability": ("reset_capability_executor", None),
    # ... 共 70+ 个模块
}
```

> **TS 注意**：每个模块的 `reset_*` 函数必须保留同名导出，或建立映射表。这是测试独立性的核心保障。

### 3.3 `from X import Y` 在测试函数内导入模式

```python
def test_dispatch_agents_with_real_cell(self):
    from l2.l2_shell import dispatch, reset_state
    from l3.agent.scout import reset_pool
    from l3.agent_terminal import reset_terminals
    from l3.cell import get_cell, reset_cells

    reset_state()
    reset_terminals()
    reset_pool()
    reset_cells()

    try:
        cell = get_cell("e2e-test-cell", ["."])
        cell.add_agent("alpha", role="writer", territory=["."], auto_boot=True)
        _wait_for_agent("alpha")
        r = dispatch("/agents")
        # ... assertions
    finally:
        reset_terminals()
        reset_pool()
        reset_cells()
        reset_state()
```

**模式特征**：
- **为什么在函数内导入**：避免模块级导入导致 conftest 重置时无法捕获副作用
- **TS 等价物**：使用动态 `import()` 或 `await import()`（ESM）；或确保模块级 `import` + `beforeEach` reset

### 3.4 Fixture 模式

```python
@pytest.fixture
def irq():
    """Fresh InterruptController with no PMU."""
    return InterruptController(cell_id="test-cell", pmu=None)


@pytest.fixture
def irq_with_pmu():
    """InterruptController with a mock PMU."""

    class FakePmu:
        def __init__(self):
            self.counts = {}

        def increment(self, name: str, delta: int = 1):
            self.counts[name] = self.counts.get(name, 0) + delta

    pmu = FakePmu()
    ctrl = InterruptController(cell_id="test-cell", pmu=pmu)
    return ctrl, pmu
```

**TS 等价物（Vitest）**：
```typescript
const createFakePmu = (): { counts: Record<string, number> } => ({
  counts: {},
  increment(name: string, delta = 1) {
    this.counts[name] = (this.counts[name] || 0) + delta;
  },
});

const irq: () => InterruptController = () =>
  new InterruptController({ cellId: "test-cell", pmu: null });
```

### 3.5 Parameterized Tests

```python
@pytest.mark.parametrize(
    "line",
    [
        "/help",
        "/lang",
        "/history",
        "/sysinfo",
        "/help status",
    ],
)
def test_builtin_results_are_json_safe(session: ShellSession, line: str) -> None:
    """Pure shell built-ins return JSON-safe dicts with success=True."""
    result = dispatch(line, session)
    _assert_json_safe(result)
    assert result.get("success") is True
```

**TS 等价物（Vitest）**：
```typescript
it.each([
  "/help",
  "/lang",
  "/history",
  "/sysinfo",
  "/help status",
])("pure shell built-ins return JSON-safe dicts with success=True — %s", (line) => {
  const result = dispatch(line, session);
  expect(result).toSatisfy(isJsonSafe);
  expect(result.success).toBe(true);
});
```

### 3.6 Vector-based Tests（JSON fixture 驱动）

```json
// tests/fixtures/kernel_event_vectors.json
{
  "cases": [
    {
      "name": "bounded_history_and_type_filters",
      "max_history": 2,
      "signals": [
        { "type": "TASK_DONE", "data": { "seq": 1 } }
      ]
    }
  ]
}
```

**TS 等价物**：
```typescript
import eventVectors from "./fixtures/kernel_event_vectors.json";

for (const tc of eventVectors.cases) {
  test(tc.name, () => {
    // ...
  });
}
```

> **注意**：TS 需要在 `tsconfig.json` 中添加 `"resolveJsonModule": true` 才能直接 import JSON。

### 3.7 YAML Card 测试文件

```yaml
# tests/snake_card.yaml
card:
  id: "snake-001"
  intent: "Write a production-grade Snake game..."
  domain: "."
  mode: PARALLEL_ALL
phases:
  - name: recon
    mode: PARALLEL
    steps:
      - action: scout
        target: "List the current directory structure..."
        agent: scout
```

**这些文件**：`snake_card.yaml`, `snake_complete.yaml`, `self_bootstrap.yaml`, `self_host.yaml`, `self_host_write.yaml`, `self_constantize.yaml`
- 不是 pytest 测试文件，而是 **Card 定义文件**
- TS 重写后保持 YAML 格式不变，只更新引用的 Python3 模块路径
- 加载方式在 TS 中可用 `yaml` npm 包解析

### 3.8 轮询等待模式

```python
def _wait_for_agent(agent_id: str, timeout: float = 2.0, poll: float = 0.05) -> bool:
    """Poll AgentTerminal status until IDLE or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            term = get_terminal(agent_id)
            if term and term.status.name == AGENT_STATUS_IDLE:
                return True
        except Exception:
            pass
        time.sleep(poll)
    return False
```

**TS 等价物**：
```typescript
async function waitForAgent(
  agentId: string,
  timeout = 2000,
  poll = 50,
): Promise<boolean> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const term = getTerminal(agentId);
      if (term && term.status.name === AGENT_STATUS_IDLE) {
        return true;
      }
    } catch {
      // ignore
    }
    await new Promise((resolve) => setTimeout(resolve, poll));
  }
  return false;
}
```

### 3.9 `try/finally` 资源清理模式

```python
try:
    cell = get_cell("e2e-test-cell", ["."])
    cell.add_agent("alpha", role="writer", territory=["."], auto_boot=True)
    _wait_for_agent("alpha")
    r = dispatch("/agents")
    # ...
finally:
    reset_terminals()
    reset_pool()
    reset_cells()
    reset_state()
```

**TS 等价物**：
```typescript
try {
  const cell = getCell("e2e-test-cell", ["."]);
  cell.addAgent({ agentId: "alpha", role: "writer", territory: ["."], autoBoot: true });
  await waitForAgent("alpha");
  const r = dispatch("/agents");
  // ...
} finally {
  resetTerminals();
  resetPool();
  resetCells();
  resetState();
}
```

### 3.10 测试 Runner（Slice 调度）

```python
# runner.py — 按层切片调度
SLICES: dict[str, list[str]] = {
    "infra": ["tests/infra"],
    "l1": ["tests/l1"],
    "l2": ["tests/l2"],
    "l3-fast": [
        "tests/l3/cell",
        "tests/l3/agent",
        # ...
    ],
    # ...
}
FULL_ORDER = ["infra", "l1", "l2", "l3-fast", "l3-mid", "l3-slow", ...]
```

**TS 等价物**：
```typescript
const SLICES: Record<string, string[]> = {
  infra: ["tests/infra"],
  l1: ["tests/l1"],
  l2: ["tests/l2"],
  "l3-fast": ["tests/l3/cell", "tests/l3/agent", "..."],
  // ...
};

const FULL_ORDER = ["infra", "l1", "l2", "l3-fast", ...];
```

---

## 四、TS 重写注释模板（Copiable Patterns）

### 4.1 测试文件头部模板

```typescript
/**
 * L1 Kernel — core module importability and API tests.
 *
 * Tests verify that every public API exported by l1/kernel is importable
 * and returns the expected object shape. Import tests use pass assertions
 * because the act of importing IS the test — no further runtime behavior.
 */
```

### 4.2 测试类模板

```typescript
describe("TerritoryConstitution", () => {
  /**
   * Default construction — verifies zero-state invariants.
   */
  it("should initialize with empty territories and default v1 values", () => {
    const tc = new TerritoryConstitution();
    expect(tc.territories).toEqual({});
    expect(tc.version).toBe(1);
    expect(tc.defaultReputation).toBeGreaterThan(0);
    expect(tc.tokenBudget).toBeGreaterThan(0);
  });
});
```

### 4.3 Fixture 模板

```typescript
const createFakePmu = (): FakePmu => ({
  counts: new Map<string, number>(),
  increment(name: string, delta = 1) {
    const current = this.counts.get(name) || 0;
    this.counts.set(name, current + delta);
  },
});
```

### 4.4 轮询等待模板

```typescript
/**
 * Poll AgentTerminal status until IDLE or timeout.
 *
 * Replaces fixed time.sleep() with responsive polling to reduce CI
 * wall-clock time. Returns true if agent reached IDLE within timeout,
 * false otherwise.
 */
async function waitForAgent(
  agentId: string,
  timeout = 2000,
  poll = 50,
): Promise<boolean> {
  // ...
}
```

### 4.5 段落分隔模板

```typescript
// ═══════════════════════════════════════════════════════════════════
// TerritoryConstitution
// ═══════════════════════════════════════════════════════════════════

// ── Construction ──

// ── parse_territory / render_territory ──
```

---

## 五、TS 重写关键映射表

### 5.1 Python3 → TypeScript 概念映射

| Python3 | TypeScript | 备注 |
|--------|-----------|------|
| `def test_xxx(self):` | `it("...", () => { ... })` | 方法名 → 描述字符串 |
| `class TestXxx:` | `describe("Xxx", () => { ... })` | 类 → describe 块 |
| `assert a == b` | `expect(a).toBe(b)` | 严格相等 |
| `assert a is b` | `expect(a).toBe(b)` | 引用相等 |
| `assert isinstance(a, list)` | `expect(Array.isArray(a)).toBe(true)` | 类型检查 |
| `assert hasattr(x, "y")` | `expect(x).toHaveProperty("y")` | 属性存在 |
| `assert "key" in d` | `expect(d).toHaveProperty("key")` | 字典键 |
| `with tempfile.TemporaryDirectory():` | `fs.mkdtempSync()` | 临时目录 |
| `@pytest.fixture` | `beforeEach` / `vi.fn()` | 测试 fixture |
| `@pytest.mark.parametrize` | `it.each([...])` | 参数化 |
| `sys.modules[mod_name]` | `globalThis.__modules?.[name]` | 模块注册表 |

### 5.2 项目特有 API 映射

| Python3 API | TS 等价物 | 备注 |
|-----------|----------|------|
| `get_constitution()` | `getConstitution()` | 单例获取 |
| `reset_constitution()` | `resetConstitution()` | 单例重置 |
| `get_cell(id, territories)` | `getCell(id, territories)` | Cell 创建 |
| `dispatch("/command")` | `dispatch("/command")` | L2 Shell 调度 |
| `cell.execute_card(text)` | `cell.executeCard(text)` | Card 执行 |
| `cell.add_agent(id, role, ...)` | `cell.addAgent({agentId, role, ...})` | 注册 Agent |
| `get_terminal(id)` | `getTerminal(id)` | AgentTerminal |
| `get_memory()` | `getMemory()` | MemoryManager |
| `get_vfs()` | `getVfs()` | VFS |
| `get_limiter()` | `getLimiter()` | ResourceLimiter |
| `irq.trigger(n)` | `irq.trigger(n)` | IRQ 触发 |
| `irq.dispatch_pending()` | `irq.dispatchPending()` | IRQ 调度 |
| `irq.register(n, name)` | `irq.register(n, name, {priority})` | IRQ 注册 |
| `irq.mask(n)` / `irq.unmask(n)` | `irq.mask(n)` / `irq.unmask(n)` | IRQ 掩码 |
| `irq.stats()` | `irq.stats()` | IRQ 统计 |

### 5.3 命名约定转换

| Python3 风格 | TS 风格 | 示例 |
|-------------|--------|------|
| `snake_case` | `camelCase` | `get_paths()` → `getPaths()` |
| `UPPER_SNAKE` | `UPPER_SNAKE`（常量保留） | `IRQ_TABLE_SIZE` 不变 |
| `_private` | `_private` | `_table` 不变 |
| `class TestXxx:` | `describe("Xxx")` | 类名 → describe 标签 |
| `def test_xxx_yyy():` | `it("xxx yyy", ...)` | 方法名 → 描述句 |
| `setUp()` | `beforeEach()` | 测试前钩子 |
| `setup_method()` | `beforeEach()` | pytest 4.x 风格 |

### 5.4 单例 Reset 模块映射（TS 版本）

TS 重写后，`_RESETS` 表需要转为 `Map<string, () => void>`：

```typescript
const RESET_MAP: Map<string, () => void> = new Map([
  ["l4.api.api_gateway", stopApi],
  ["l4.ci_review", resetService],
  ["l1.kernel.capability", resetCapabilityExecutor],
  ["l3.card.approval_gate", resetGate],
  // ... 完整迁移 conftest.py 的 _RESETS 表
]);
```

---

## 六、特殊测试类型速查

| 测试类型 | 示例文件 | 特点 |
|----------|---------|------|
| Importability | `test_kernel_core.py` | 仅验证模块可导入，pass 即通过 |
| Params 完整性 | `test_params_integrity.py` | 验证魔法数字已集中到 params/ |
| 层导入约束 | `test_layer_imports.py` | AST 解析验证无向上导入 |
| IRQ 测试 | `test_interrupt.py` | 17 个内置 IRQ + 注册/触发/调度/掩码 |
| 持久化测试 | `test_persistence.py` | 版本迁移 + PersistableMixin + 并发 |
| E2E Shell | `test_l2_shell_e2e.py` | 真实 Cell+Agent + 命令调度 |
| 轮询等待 | 多文件 | `_wait_for_agent()` 模式 |
| Vector 驱动 | `fixtures/*.json` | 数据驱动测试 |
| YAML Card | `snake_card.yaml` | 非 pytest，Card 定义 |
| 性能基准 | `benchmarks/*.py` | `pytest-benchmark` 集成 |

---

## 七、注释完整性改进建议（TS 重写时强制执行）

### 7.1 必须补齐的注释类型

1. **每个 `.ts` 测试文件必须有模块级 JSDoc**：说明被测模块 + 测试范围
2. **每个 `describe()` 块必须有类级 JSDoc**：说明该类测试的职责边界
3. **每个 `it()`/`test()` 必须有 JSDoc**：说明测试意图（不是断言内容）
4. **每个 `beforeEach`/`afterEach` 必须有 JSDoc**：说明资源生命周期

### 7.2 禁止事项

- ❌ 禁止无注释的 `it()` / `test()`（即使是 pass 测试）
- ❌ 禁止用中文写注释（AGENTS.md 要求）
- ❌ 禁止跳过模块级 docstring
- ❌ 禁止无注释的参数化测试数据数组（每个 case 应有简短说明）

### 7.3 推荐做法

- ✅ 段落注释：`// ── Section Name ──`
- ✅ 大分区：`// ═══════════════════════`
- ✅ 行内注释只用于解释"为什么"，不解释"做什么"
- ✅ 每个 fixture 用 JSDoc 说明其创建的对象和用途

---

## 八、完整注释示例（从 Python3 到 TS）

### Python3 原始（`test_interrupt.py`）

```python
# ── Built-in IRQ tests ──


class TestBuiltinIrqs:
    """17 built-in IRQs registered at init (0-16, incl. cell.rollback)."""

    def test_16_builtin_irqs(self, irq):
        """IRQs 0-16 pre-registered (17 total, cell.rollback added as IRQ16)."""
        stats = irq.stats()
        assert stats["registered_irqs"] == 17

    def test_builtin_nmi_priorities(self, irq):
        """IRQ 0-3 are NMI priority."""
        for n in range(4):
            slot = irq._table.get(n)
            assert slot is not None
            assert slot.priority == IrqPriority.NMI, f"IRQ{n} should be NMI"
```

### TypeScript 等价物

```typescript
// ── Built-in IRQ tests ──

describe("Built-in IRQs", () => {
  /**
   * 17 built-in IRQs registered at init (0-16, incl. cell.rollback).
   */
  it("should register 17 IRQs (0-16) including cell.rollback as IRQ16", () => {
    const stats = irq.stats();
    expect(stats.registeredIrqs).toBe(17);
  });

  /**
   * IRQ 0-3 are NMI priority.
   */
  it("should assign NMI priority to IRQ 0-3", () => {
    for (let n = 0; n < 4; n++) {
      const slot = irq._table.get(n);
      expect(slot).toBeDefined();
      expect(slot!.priority).toBe(IrqPriority.NMI);
    }
  });
});
```

---

## 附录：注释质量评分标准（供 TS 重写验收使用）

| 维度 | 满分 | 扣分条件 |
|------|------|----------|
| 模块 docstring | 20% | 缺失=0分 |
| 类/描述块 docstring | 25% | 每缺一个扣 1 分 |
| 方法/it() docstring | 35% | 每缺一个扣 0.5 分 |
| 段落分隔注释 | 10% | 主要分区缺失扣分 |
| 行内注释质量 | 10% | "为什么"缺失扣分 |

TS 重写验收时，每个测试文件的目标评分应 ≥ 85/100。
