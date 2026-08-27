---
description: Format and lint-fix the Praxis codebase (ruff format + ruff check --fix)
---
Format and fix the codebase:

- Format: `ruff format systems/python-reference-runtime/ tests/` (or `make format`)
- Auto-fix lint: `ruff check --fix systems/python-reference-runtime/ tests/` (or `make lint-fix`)
- Verify: `make format-check` / `make lint`
