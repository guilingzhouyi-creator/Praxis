# Praxis — Agent OS (v0.4.2 "Aether")

Python 3.11+ Agent OS for orchestrating LLM-based agents. Five-layer architecture from bare-metal kernel to user CLI.

> **指针索引** — 本文件不重复规则，只给“任务→读哪段→用哪工具→过哪门禁”。改子系统前读对应段，探针 ≤3 文件。`CLAUDE.md` 为 Claude 薄指针，规则以本文件为准。

## 索引 — 任务→文件→段落（读指定段即可，无需全读）

| 任务 | 指向文件 | 读哪段 | 工具示例 |
|---|---|---|---|
| 架构总览/分层地图 | `docs/architecture/README.md` | `## System overview` + `## Layer documents` (1-100) | `read docs/architecture/README.md 1 100` |
| L1 内核(进程/事件/门禁/VFS/端口) | `docs/architecture/l1-kernel.md` + `src/l1/kernel/params/` + `src/l1/kernel/ports/` | 全文 + `params/` 常量、`ports/` ABC | `grep -r Port src/l1/kernel/ports` |
| L2 Shell/协议 | `docs/architecture/l2-shell.md` + `l2-shell-engine.md` + `src/l2/l2_shell/` | `## Shell family` / `## Target Shell Engine` | `read src/l2/l2_shell/__main__.py` |
| L3 Card/Scheduler/L3A | `l3-card-lifecycle.md` + `l3-scheduler.md` + `l3a-central.md` | Card produce→archive、5D 调度、session/ask | `read src/l3/cell/peers/l3a/` |
| 记忆/技能 | `l3-memory.md` + `skill-system.md` | R1-4 + 侧通道、`authorize_write`/DAG | `read docs/architecture/skill-system.md 1 60` |
| 工具/沙盒/差异 | `l3-tools.md` + `sandbox-diff.md` + `config/tools.yaml` | ToolSpec 注册、9步 pipeline、hunk 归因 | `read config/tools.yaml 1 40` |
| 安全/门禁/执行证据 | `security-evidence.md` + `src/l1/kernel/constitution.py` | 4态 harness、`GateChain` G1-5、evidence | `read src/l1/kernel/gatechain/` |
| 提交/完成判定/推送 | `docs/workflow/commits.md` | `## Message contract`(8-71) `## CompletionJudge`(72-84) `## Mainline net-delta`(95-144) `## Push discipline`(145-166) + `config/discovery/commits.yaml:17-60` | `read docs/workflow/commits.md 8 44` |
| 分支/堆积门禁 | `docs/workflow/branching.md` | `## 2 Branch model` + `## 4 Double-green` + `## 8 Branch accumulation` | `read docs/workflow/branching.md 20 70` |
| 工作树/豁免/DoD | `docs/workflow/code-of-conduct.md` | `## Worktree gate` + `## Gate waivers` + `## Definition of done` | `read docs/workflow/code-of-conduct.md 9 42` |
| 并行协作 | `docs/workflow/collaboration.md` | `## Parallel collaboration` | `read docs/workflow/collaboration.md 1 60` |
| 测试/切片/单测污染 | `tests/runner.py:28-60` + `tests/conftest.py:_RESETS` + `pyproject.toml:78-93` | `SLICES`/`FULL_ORDER`/`addopts -n auto --dist loadfile` **切片优先，禁 `pytest -n 0`/全量单线程** | `python tests/runner.py --list-slices` |
| Lint/钩子/门禁形态 | `.githooks/pre-commit:1-69` + `.githooks/commit-msg:100-207` + `Makefile:6-35` | staged ruff、Conventional、Co-Authored-By | `read .githooks/commit-msg 132 173` |
| 多语言构建 | `crates/l1-kernel-rs/Cargo.toml` + `packages/protocol-ts/README.md` + `.github/workflows/multilang.yml` | Rust 契约 / TS 镜像消费 `tests/fixtures/protocol_v1_records.json` | `make language-check` |
| 配置/参数治理 | `docs/configuration/overview.md` + `src/l1/kernel/settings.py:DEFAULTS` | 三层配置：params→commits.yaml→praxis.yaml | `grep DEFAULTS src/l1/kernel/settings.py` |
| 关键入口 | `src/main.py` · `src/l5/cli.py` · `src/l1/kernel/os.py` · `src/l3/tool_system/tool_pipeline.py` · `src/l3/card/card_registry.py` · `src/l3/boot/boot.py:7步` | — | `read src/main.py 1 40` |

## 测试 — 切片优先（禁 `pytest -n 0` / 全量单线程，反复提示）

> **切片优先**：改哪层跑哪 slice；全量仅 `G2 CompletionJudge` 前最终验证。`pyproject.toml:78-93` 已设 `-n auto --dist loadfile`（并行），`-n 0` 为 CI 显式 pin，本地禁单线程；WSL 用 `--no-xdist`。

| 改动路径 | 跑此 slice | 工具 |
|---|---|---|
| `src/l1/**` | `l1` | `python tests/runner.py --slice l1 --no-xdist` |
| `src/l2/**` | `l2` | `python tests/runner.py --slice l2 --no-xdist` |
| `src/l3/cell/**` 等快速域 | `l3-fast` | `python tests/runner.py --slice l3-fast` |
| `src/l3/**` 慢域 | `l3-slow`（=`make test-extended` 仅此） | `python tests/runner.py --slice l3-slow` |
| `src/l4/**` | `l4-fast` / `l4-lsp` | `python tests/runner.py --slice l4-fast` |
| `tests/**` / `infra` | `infra` 或对应域 | `python tests/runner.py --slice infra` |
| 不确定 | `--list-slices` 查表；`python -m pytest <单文件> -x -q` 仅单文件 | `python tests/runner.py --list-slices` |

- **反复提示模板**（每步 echo，未勾不进下一步）：`切片: <slice> ☐未跑/✅已跑 → 全量 ⛔禁 | 门禁: G2 未绿→G3/G4 阻断`

## 命令 — 极简（其余查 `Makefile:行` / `pyproject.toml:行`）

```bash
pip install -e ".[test]"                                          # via .venv/bin/python，worktree 复用主树 .venv
python src/main.py boot|health|status|ps|card                     # 1-2
python -m l2.l2_shell                                             # 3  (package with __main__.py)
python tests/runner.py --list-slices                              # 查可用 slice
python tests/runner.py --slice l3-fast --no-xdist                  # 单 slice（WSL 并行启动慢，推荐 --no-xdist）
python -m pytest tests/l1/test_kernel.py -x -q                   # 单文件（禁 `pytest tests/ -n 0` 全量单线程）
make test  # = batch1 除 l3-slow
make test-extended  # = batch2 仅 l3-slow
make test-all  # 全量仅最终门禁前
make lint|format|typecheck|coverage  # coverage 阈值 60，忽略 bench_card.py
make precommit  # style only；治理门在 .githooks/；PR CI 仅 lint 变更文件，全量在 nightly
make doc-stats  # 改文件/常量/路由后必跑，否则 CI doc-stats 漂移失败
make language-check  # ts-test+typecheck + rust-test+fmt+clippy
make hooks && make push-both  # worktree 后必设 hooks；主干推送必双远端（origin=GitCode）
```

## 脚手架 — 打勾式 Checklist（复制到任务描述，完成一项勾一项，未勾不进下一步）

```md
- [ ] 1 定向 — 从上表选 1 行，read 指定段（例：`read docs/workflow/commits.md 8 44`）
- [ ] 2 探针 — grep/read ≤3 文件定位入口/参数/用例（例：`grep trace_id src/l3/error_bus`）
- [ ] 3 改码 — 小步改，不硬编码：魔数进 `src/l1/kernel/params/`，新工具注册 `config/tools.yaml:ToolSpec`
- [ ] 4 自检 — 切片优先：`python tests/runner.py --slice <映射> --no-xdist`（禁 `pytest -n 0` 全量），`make lint` + `make coverage`；贴 `切片: l3-fast ✅ 已跑 → 全量 ⛔禁` 反馈
- [ ] 5 门禁 — `bash scripts/sh/verify-completion.sh` → 需 COMPLETE（11维）才算 done；G2 未绿则 G3/G4 自动红
- [ ] 6 合并 — `bash scripts/sh/verify-local-merge.sh` → `git merge --no-ff` → 触架构则同 commit 更 `docs/architecture/README.md`；每步 echo `切片/门禁` 状态
```

## 脚手架 — 门禁联动（前一门未绿，后一门自动红；任一 `✗/VIOLATIONS/INCOMPLETE/REJECTED` 即阻断）

```
G0 pre-commit (staged ruff --fix + size + snake_case) 
  → G1 commit-msg (Conventional ≤72 + Co-Authored-By=`python scripts/py/detect_agent.py --json` 真值校验) 
  → G2 CompletionJudge (11维 `verify-completion.sh`；需先切片绿，全量单线程禁) 
  → G3 net-delta (≥1000，3锁：去注释/对称删除/卫生天花板) 
  → G4 doc-stats/CI/multilang (变更文件未跑 `make doc-stats` 即漂移失败) 
  → G5 push-both (origin GitCode + github 三方一致)
  切片联动：改 `src/l1/**`→`G2:l1` 未跑则 G3 阻断；改 `l3/**`→`G2:l3-fast/mid/slow` 未跑则阻断；反复提示 `切片: <slice> ☐/✅ → 全量 ⛔禁`
```

- 反馈格式固定：`门禁: Gx 绿/红 — 原因 — fix: <命令>`，便于模型 `grep "VIOLATIONS|INCOMPLETE|REJECTED|✗"` 快速定位
- 豁免需用户显式授权，二者不互通：`WHERE` 主树修改豁免（`check-worktree.sh`）/ `WHEN` 提前合入豁免（`MERGE_GATE_SKIP=1 MERGE_GATE_REASON=<why>`）— 永不自授

## 约定 — 指针（不复述，只给位置）

- 魔数/常量 → `src/l1/kernel/params/`，新模块导出 `kernel/__init__.py:__all__`，新配置默认值 `kernel/settings.py:DEFAULTS`
- 并发锁 `threading.RLock`（可重入）/ `Lock`（扁平）；`trace_id` 在 `src/l3/error_bus/core.py:get_trace_id/trace_scope`
- 禁 `from services import` 于 `kernel/`；工具注册 `config/tools.yaml:ToolSpec`；禁裸 `except:`；字符串双引号 120
- Prompt 模板为数据 `src/l1/kernel/prompts.py:_DEFAULTS`，`config/praxis.yaml` 覆写；注释英文基线，模块/类/公开函数需 docstring

## OpenCode

`opencode.json` 启用 MCP：`serena`(120s) · `sqlite`(memory_graph.db) · `context7`(remote) · `github`(local npx)；`docker` 禁用。`instructions` 未委托，本文件为准。
