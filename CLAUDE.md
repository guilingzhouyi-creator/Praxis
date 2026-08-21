# CLAUDE.md — 指向 AGENTS.md 的薄指针（不复述规则）

> **改代码前必读**：本文件只给指针，规则以 `AGENTS.md` 为准。按表读指定段，探针 ≤3 文件，用打勾式/门禁联动脚手架反馈。

## 指针 — 任务→读哪段（用 `read` 快速定位）

| 任务 | 读哪段 | 工具 |
|---|---|---|
| 定向/分层地图 | `AGENTS.md:## 索引` + `docs/architecture/README.md:1-100` | `read AGENTS.md 10 35` |
| 提交/完成判定 | `AGENTS.md:## 索引` → `docs/workflow/commits.md:8-84` + `config/discovery/commits.yaml:17-60` | `read docs/workflow/commits.md 8 44` |
| 工作树/豁免/DoD | `AGENTS.md:## 索引` → `docs/workflow/code-of-conduct.md:9-42` | `read docs/workflow/code-of-conduct.md 9 42` |
| 测试/切片/污染 | `AGENTS.md:## 测试 — 切片优先` + `tests/runner.py:28-60` + `tests/conftest.py:_RESETS` | 切片优先，禁 `pytest -n 0`/全量；G2 需先切片绿 | `python tests/runner.py --slice l3-fast --no-xdist` |
| 钩子/门禁形态 | `AGENTS.md:## 脚手架` → `.githooks/commit-msg:132-173` | `read .githooks/commit-msg 132 173` |

## 脚手架 — 复用 AGENTS.md（打勾式 + 门禁联动，反复提示切片）

- 按 `AGENTS.md:## 脚手架 — 打勾式 Checklist` 逐项打勾（6 步），未勾不进下一步；第4步必贴 `切片: <slice> ✅/☐ → 全量 ⛔禁`
- 按 `AGENTS.md:## 脚手架 — 门禁联动` 逐门禁验证，任一 `✗/VIOLATIONS/INCOMPLETE` 即阻断，回 `grep "VIOLATIONS|INCOMPLETE"` 定位；G2 未切片绿则 G3/G4 自动红
- 反馈格式：`门禁: Gx 绿/红 — 原因 — fix: <命令>` + `切片: l3-fast ✅ 已跑`，不自授豁免（`WHERE`/`WHEN` 二豁免需用户显式）；每步 echo 切片/门禁状态

## 极简命令（全量见 `AGENTS.md:## 命令` / `## 测试 — 切片优先`）

```bash
pip install -e ".[test]" && python src/main.py boot|health|status
python tests/runner.py --slice l3-fast --no-xdist  # 切片优先，禁 pytest -n 0 全量；单文件用 -x -q
```

## LLM

默认 `ollama/codellama:7b@11434`，覆写见 `AGENTS.md:## 索引` → `config/praxis.yaml`。`AGENTS.md:## OpenCode` 为 OpenCode MCP 清单。
