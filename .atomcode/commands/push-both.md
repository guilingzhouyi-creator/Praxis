---
description: Push current branch to BOTH remotes (origin=GitCode + github=GitHub) via scripts/sh/push-both.sh — required for main
---
Push the current branch to both remotes using the project's dual-remote script:

- Run: `bash scripts/sh/push-both.sh` (inside the WSL dev environment)
- On Windows shell, invoke via WSL:
  `wsl -d Ubuntu -- bash -c "cd /home/guiling/dev/praxis && bash scripts/sh/push-both.sh"`
- Pushing main to only ONE remote silently skips CI — both must be pushed.
- Before pushing, confirm tests pass (`python -m pytest tests/ -x -q`) and CHANGELOG is updated.
