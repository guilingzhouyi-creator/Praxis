---
name: completion-judge
description: Use when declaring a task complete or asked "is it really done?" — verify via the CompletionJudge machine verdict (gate-merge.sh completion, 11 dimensions); the machine decides "done", not the agent via the CompletionJudge machine verdict (gate-merge.sh completion, 11 dimensions) — the machine decides "done", not the agent. Use when declaring a task complete, before merge/push, or when asked "is it really done?".
disable-model-invocation: true
---

## Machine verdict first

The agent does NOT decide "done" — the machine does. Before declaring a
task complete, run the judge and only a `COMPLETE` verdict authorizes
"done".

- Run: `bash scripts/sh/gate-merge.sh completion`
  (WSL: `wsl -d Ubuntu -- bash -c "cd /home/guiling/dev/praxis && bash scripts/sh/gate-merge.sh completion"`)
- On `INCOMPLETE` the judge prints the **evidence gap** (which check
  failed and why) — keep working until every check is green.

## The 11 dimensions

| # | Check | Gate |
|---|---|---|
| 1 | Full test suite | `pytest tests/` green |
| 2 | Coverage | fail-under (default 60) |
| 3 | Net code delta | `gate-merge.sh mainline` (three locks) |
| 4 | Doc-stats | `check_doc_stats.py` drift clean |
| 5 | Lint + type | `ruff check/format` clean |
| 6 | Dependency CVEs | `pip-audit` (skipped if not installed) |
| 7 | Complexity | `long_functions` ≤ 12 (>200 lines) |
| 8 | Import cycles | `import_cycle_check.py` |
| 9 | Singleton drift | `check_singletons.py` vs `_RESETS` |
| 10 | CHANGELOG freshness | `check_changelog.py` |
| 11 | Doc-index | `check_doc_index.py` |

## Ratchet property

- A pass never reopens: once a check is green it stays green.
- Every run is logged to `.praxis/judge-runs.jsonl`; the aggregate
  dashboard lives at `docs/judge-stats.md` (see `judge-stats.sh`).
- Partial verification: `--skip=tests,coverage` for fast feedback; env
  switches `COMPLETION_*` per check.
