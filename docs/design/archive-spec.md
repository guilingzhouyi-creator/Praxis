# 档案库统一基准 — 题头打标 + 指针 DSL

> **状态**: 基准 v1.2 | **生效**: 2026-08-29 | **适用**: `docs/` 全域归档（含 `design`/`review`/`decision`/`issue` 等）

## 1. 全宗与文件夹归属（统一基准）

| 全宗号 | 中文 | 保管期限 | 活跃库（tracked） | 归档库（ignored, `.gitignore:/docs/design/archive/`） | 说明 |
|---|---|---|---|---|---|
| `DESIGN` | 设计 | 永久 | `docs/design/*.md` | `docs/design/archive/design/YYYY-MM/` | 仅设计类 |
| `REVIEW` | 评审 | 长期(10年) | `docs/design/reviews/`（已清空，归档后仅留索引） | `docs/design/archive/review/YYYY-MM/` | 含 `l1-l5` 评审与专项 |
| `DECISION` | 决策 | 永久 | `docs/decisions/*.md` | `docs/decisions/archive/`（如需）或 `docs/design/archive/DECISION/` 已归并 | 决策类不归入 `DESIGN` |
| `ISSUE` | 事项 | 短期(3年) | `docs/issues/*.md` | 同上 |  |
| `ARCHITECTURE` | 架构 | 永久 | `docs/architecture/*.md` | `docs/architecture/archive/`（如需） |  |
| `ROADMAP` | 路线图 | 长期 | `docs/roadmaps/*.md` | 同上 |  |

**归属校正**：此前 `docs/design/archive/decisions/` 与 `docs/design/archive/issues/` 为**错误归属**（设计全宗混入决策/事项），已移除；`migrate_api_v2.py` 非档案，已移除。设计档案仅保留 `DESIGN/` 与 `REVIEW/`。

## 2. 题头打标（中国档案馆 GB/T 9705 + DA/T 18）

每个归档/活跃文档 frontmatter 必须含：

```yaml
---
pointer: ARCH-DESIGN-2026-08-05-012  # 指针，DSL 主键（见 §3）
档号: DESIGN-2026-永久-012           # 档号 = 全宗号-年度-保管期限-件号
全宗号: DESIGN
年度: 2026
保管期限: 永久  # 永久 / 长期 / 短期
题名: Praxis 地基缺口施工规划
责任者: L3
形成时间: 2026-08-05
载体: md
页数: 311
密级: 内部
fonds: DESIGN
series: archive  # active/archive
status: archived
---
```

## 3. 指针 DSL

`pointer` 为**唯一检索键**，`POINTERS.json` 为机器索引，`README.md` 为人读索引。

### 3.1 指针编码

- 活跃：`DESIGN-YYYY-MM-DD-NNN`
- 归档设计：`ARCH-DESIGN-YYYY-MM-DD-NNN`
- 归档评审：`ARCH-REVIEW-YYYY-MM-DD-NNN`
- 归档决策：`ARCH-DECISION-YYYY-MM-DD-NNN`

### 3.2 DSL 查询（基于 `POINTERS.json`）

```bash
# 按档号
jq '.[] | select(.pointer=="ARCH-DESIGN-2026-08-05-012")' docs/design/POINTERS.json
# 按全宗+年度
jq '.[] | select(.fonds=="DESIGN" and .year=="2026")' docs/design/POINTERS.json
# 按题名
jq '.[] | select(.title | contains("CI"))' docs/design/POINTERS.json
# 按保管期限
jq '.[] | select(.retention=="永久")' docs/design/POINTERS.json
# 组合
jq '.[] | select(.fonds=="REVIEW" and .year=="2026-07")' docs/design/POINTERS.json
```

前端/脚本可直接 `fetch('docs/design/POINTERS.json').then(j=>j.filter(...))`。

### 3.3 恢复

```bash
git log --all --diff-filter=D -- docs/design/foundation-gaps-plan.md
git show <commit>:docs/design/foundation-gaps-plan.md > /tmp/restore.md
# 或磁盘直读（主树）
cat docs/design/archive/DESIGN/2026-08/2026-08-05_design_foundation-gaps-plan.md
```

## 4. 文件夹与文档命名规范

### 4.1 文件夹

- 一律 `lowercase kebab-case`（`project-structure.md`），归档库内按 `全宗/YYYY-MM/` 二级
- 示例：`archive/DESIGN/2026-08/`、`archive/REVIEW/2026-07/`

### 4.2 文档

- 活跃：`kebab-case.md`（无 `praxis-` 前缀，已统一），例 `ci-automation-design.md`
- 归档：`YYYY-MM-DD_design_<kebab>.md` 或 `YYYY-MM-DD_review_<kebab>.md`，前缀 `design_`/`review_` 统一，`YYYY-MM-DD` 为形成时间
- 档号与文件名分离：档号在 frontmatter，文件名仅 `YYYY-MM-DD_<type>_<kebab>.md`，指针与档号一一对应

## 5. 索引

- 人读：`docs/design/README.md`（三表：活跃/归档设计/归档评审）
- 机器：`docs/design/POINTERS.json`（含 `pointer/档号/全宗号/年度/保管期限/题名/责任者/形成时间/载体/文件路径`）
- 磁盘镜像：`docs/design/archive/INDEX.md`（同 README 内容，ignored）

## 5. 索引效率

| 方案 | 48 条 | 10k 条 | 适用 |
|---|---|---|---|
| `jq` 线性 | 0.0010ms | 0.47ms | <1k |
| `hash` O1 | 0.0001ms | 0.0045ms | 指针 |
| `SQLite` 索引 | 0.04ms | 0.02ms | 10k+ |
