# _outgoing — 归档预存区（archival pre-storage）

> 完成的文档（`construction: closed`）放入本目录后，提交时由 doc gate 自动归档：
> 重指向 frontmatter（`ARCH-*` 指针、档号、`series: archive`、`status: archived`、
> `original_name`）→ 移入对应全宗归档目录 → 删除活跃文件 → 重建 POINTERS 索引。

## 用法

1. 把要归档的文档（DESIGN 或 ROADMAP 全宗，题头含 `construction: closed`）
   移动到这里：`git mv docs/roadmaps/foo.md docs/design/_outgoing/foo.md`；
2. `git add docs/design/_outgoing/foo.md` 并提交——pre-commit 的 doc gate 会调用
   `scripts/py/doc_archive.py --staged --fix` 自动完成归档（活跃文件删除随提交落地）。

手动归档（等价）：`python scripts/py/doc_archive.py --file docs/design/_outgoing/foo.md --fix`

## 规则

- **触发条件**：`fonds` ∈ {DESIGN, ROADMAP} 且 `construction: closed`——归档是
  完成态驱动的，其他状态会被拒绝。
- **落点**：DESIGN → `archive/001-design/2026/永久/`；ROADMAP →
  `archive/003-roadmap/2026/长期/`（档号顺延，从不复用）。
- **不满足条件的文件**会阻断提交（gate 报错），不会静默移动。
- 归档目录被 `.gitignore` 忽略：内容保留在主树磁盘 + git 删除历史
  （`git log --all --diff-filter=D`），与归档库既有策略一致。
