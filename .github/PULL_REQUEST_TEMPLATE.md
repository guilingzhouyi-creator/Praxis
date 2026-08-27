## 变更类型 (Change type)

- [ ] `feat` 新功能 / feature
- [ ] `fix` 缺陷修复 / bug fix
- [ ] `refactor` 重构 / refactor (无行为变化)
- [ ] `ci` / `docs` / `test` 工程与文档

## 改动规模 (Diff size — 决定是否触发主树净增量门禁)

- [ ] 代码改动净增量 ≥ 1000 行(可直接合入 main)
- [ ] 代码改动净增量 < 600 行(应留在 worktree 分支累计,拒绝直接合入)
- [ ] 仅文档(docs/ 或根级文档,豁免)
- [ ] 删除主导(净增量 ≤ 0,豁免)

> 门禁规则: `bash scripts/sh/gate-merge.sh mainline main` — 见 AGENTS.md "Commit conventions"。

## 测试 (Tests)

- [ ] 新增/更新了测试(测试文件与用例数见 `codebase_stats` 输出)
- [ ] 全量测试通过: `python -m pytest tests/ -q`
- [ ] ruff / mypy 通过: `ruff check systems/python-reference-runtime/ tests/ && mypy systems/python-reference-runtime/ ...`

## 签名与提交规范 (Signature & commit conventions)

- [ ] 提交信息为英文 Conventional Commits(`type(scope): summary`, ≤72 字符)
- [ ] 每个提交带 `Co-Authored-By: <Agent> (<model>) <noreply@...>` trailer
- [ ] 本分支提交已 GPG 签名(GitCode pre-receive 要求)

## 冲突与对齐 (Conflicts & alignment)

- [ ] 已用 `bash scripts/sh/gate-merge.sh pr <branch>` 预检(签名/英文/冲突)
- [ ] 与同 merge-base 的 sibling 分支已对齐(如有)
