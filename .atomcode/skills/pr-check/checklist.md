# Praxis PR Checklist

## Commit message (enforced by `.githooks/commit-msg`)
- [ ] Message written in English (CJK characters are rejected)
- [ ] Conventional Commits format (`feat:` / `fix:` / `docs:` / `refactor:` / `chore:` …)
- [ ] `Co-Authored-By` trailer present (exempt: merge/revert commits, `--amend`)

## Incoming PR commits (check BEFORE merging)
- [ ] Every incoming commit GPG-signed:
      `git log --format='%h %G? %s' <merge-base>..<PR-head>` shows **no `N`** —
      GitCode pre-receive rejects ANY unsigned commit on main, not just the tip
- [ ] Every incoming subject is English + Conventional Commits — no CJK or
      placeholder subjects (`feat: 理解项目，准备构建`) in the merged history
- [ ] If either fails → **squash-merge** (`git merge --squash`) to one signed,
      English, CC commit, or ask the author to rewrite the branch; NEVER merge
      unsigned commits then re-sign afterwards (forces history rewrite + force-push)

## Verification gates
- [ ] Full test suite passes: `python -m pytest tests/ -x -q`
- [ ] Ruff clean: `ruff check .` (double quotes, line-length 120)
- [ ] Layer import test passes: `python -m pytest tests/infra/test_layer_imports.py -x -q`
- [ ] Params compliance passes: `python -m pytest tests/infra/test_params_compliance.py -x -q`
- [ ] No hardcoded magic numbers — use `src/l1/kernel/params/` constants
- [ ] Truncation/hash/importance literals use the `params/system.py` / `params/tool.py` constants

## API contract (if API changed)
- [ ] Routes under `/api/v2/` (breaking changes require `/api/v3/` + manifest entry)
- [ ] Manifest validated: `python -m l4.api.api_endpoints`

## Workflow
- [ ] `bash scripts/sh/check-worktree.sh` run before any `git checkout`/`git switch`
- [ ] Push to BOTH remotes: `git push origin main; git push github main`
- [ ] Feature branch double-green: branch tests AND main tests pass before merge
- [ ] Merged `feature/*` branch retained (do not delete — traceability)
