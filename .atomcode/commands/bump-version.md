---
description: Bump Praxis version atomically (pyproject + AGENTS.md + KERNEL_VERSION + tests + docs) via scripts/py/bump-version.py
---
Bump the project version in one atomic pass using the helper script:

- Preview: `python scripts/py/bump-version.py <ver> --dry-run`
- Apply: `python scripts/py/bump-version.py <ver>`
- Inside the WSL dev environment (prefer repo venv): `.venv/bin/python scripts/py/bump-version.py <ver>`
- On Windows shell, invoke via WSL:
  `wsl -d Ubuntu -- bash -c "cd /home/guiling/dev/praxis && .venv/bin/python scripts/py/bump-version.py <ver>"`
- Version rules: use patch for contract-safe additions, minor for API/behavior changes.
- After bumping, commit the single atomic change (see AGENTS.md "Contract versioning").
