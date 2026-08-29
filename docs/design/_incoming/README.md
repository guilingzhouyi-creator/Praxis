# 预存区 (Staging)

> **用途**：新入库文档的**唯一入口**。无论主树或工作树分支，提交时自动打标、归属、刷索引；违规即拦截。

## 使用

```bash
# 1. 将新文档放入预存区（任意文件名，kebab-case）
cp my-new-design.md docs/design/_incoming/

# 2. 直接提交（主树或工作树分支均可）
git add docs/design/_incoming/my-new-design.md
git commit -m "docs(docs): add new design"

# 提交时自动：
# - 补英文题头 DSL（pointer/archive_number/fonds/.../abstract）
# - 判全宗与去向（DESIGN→docs/design/*.md，REVIEW→archive/002-review/...）
# - 迁移至正确文件夹并清空预存区
# - 刷新 POINTERS.json + POINTERS.db + README 索引
```

## 规则

- **预存区** `docs/design/_incoming/` 为唯一入口，勿直接写 `docs/design/*.md`（直接写亦会被门禁校验，但预存区可自动纠偏）
- **题头** 缺失自动补，`abstract` 首段抽取（不与 `title` 重复），`pointer`/`archive_number` 自增
- **违规拦截**：缺 `title`、重 `archive_number`、`fonds` 与路径不符、`kebab` 非法 → `pre-commit` 阻断并提示 `Agent` 修复

## 门禁

`pre-commit` 调用 `scripts/py/check_doc_gate.py`（`--staged`），`--fix` 时自动迁移，`--check` 仅校验。工作树与主树共用同一钩子。
