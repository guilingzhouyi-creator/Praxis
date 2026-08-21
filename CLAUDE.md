# CLAUDE.md — 指向 AGENTS.md 的薄指针（不复述规则）

> **改代码前必读**：本文件只给指针，规则以 `AGENTS.md` 为准。按表读指定段，探针 ≤3 文件，用打勾式/门禁联动脚手架反馈。

## 指针 — 任务→读哪段（用 `read` 快速定位）

| 任务 | 读哪段 | 工具 |
|---|---|---|
| 定向/分层地图 | `AGENTS.md:## 索引` + `docs/architecture/README.md:1-100` | `read AGENTS.md 10 35` |
| 提交/完成判定 | `AGENTS.md:## 索引` → `docs/workflow/commits.md:8-84` + `config/discovery/commits.yaml:17-60` | `read docs/workflow/commits.md 8 44` |
| 工作树/豁免/DoD | `AGENTS.md:## 索引` → `docs/workflow/code-of-conduct.md:9-42` | `read docs/workflow/code-of-conduct.md 9 42` |
| 测试/切片/污染 | `AGENTS.md:## 索引` → `tests/runner.py:28-60` + `tests/conftest.py:_RESETS` | `python tests/runner.py --list-slices` |
| 钩子/门禁形态 | `AGENTS.md:## 脚手架` → `.githooks/commit-msg:132-173` | `read .githooks/commit-msg 132 173` |

## 脚手架 — 复用 AGENTS.md（打勾式 + 门禁联动）

- 按 `AGENTS.md:## 脚手架 — 打勾式 Checklist` 逐项打勾（6 步），未勾不进下一步
- 按 `AGENTS.md:## 脚手架 — 门禁联动` 逐门禁验证，任一 `✗/VIOLATIONS/INCOMPLETE` 即阻断，回 `grep "VIOLATIONS|INCOMPLETE"` 定位
- 反馈格式：`门禁: Gx 绿/红 — 原因 — fix: <命令>`，不自授豁免（`WHERE`/`WHEN` 二豁免需用户显式）

## 极简命令（全量见 `AGENTS.md:## 命令`）

```bash
pip install -e ".[test]" && python src/main.py boot|health|status
python -m pytest tests/l1/test_kernel.py -x -q  # 单文件；全量见 AGENTS.md
```

## LLM

默认 `ollama/codellama:7b@11434`，覆写见 `AGENTS.md:## 索引` → `config/praxis.yaml`。`AGENTS.md:## OpenCode` 为 OpenCode MCP 清单。
