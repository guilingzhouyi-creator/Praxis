# Commit Conventions & Mainline Gates

Full specification for the Praxis commit contract and the mainline merge
gates. `AGENTS.md` (`## Commit conventions`) carries the load-bearing
summary and indexes here; `config/discovery/commits.yaml` is the single
source of truth for the Conventional-Commits contract.

## Message contract (enforced by `.githooks/commit-msg`)

- **Messages MUST be in English** (CJK rejected).
- **Every commit MUST carry exactly ONE well-formed `Co-Authored-By`
  trailer** naming the authoring agent/model:
  `Co-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>`.
  The hook enforces: exactly one trailer (no multi-agent stacking), the
  `<Agent> (<model>) <noreply@domain>` shape, and a noreply email.
  Historical commits also used `OpenCode (deepseek-v4-flash) <noreply@opencode.ai>`.
- **Attribution is verified for TRUTH, not just shape** — `commit_scan.py`
  compares the trailer against the agents registry (`config/discovery/
  commits.yaml` `agents:`) AND the live runtime detection
  (`scripts/py/detect_agent.py`). The detector trusts EXECUTION EVIDENCE,
  never the agent's self-report and never a config file alone:
  - **DSH sessions**: the harness session log (`$DSH_SESSION_JSONL`)
    records the real `(provider, model)` route of every LLM call — written
    by the harness, uneditable by the agent inside the session. This is
    the strongest evidence and wins over any config.
  - **Config declaration** (`~/.dsh/settings.yaml`) is only a
    LOW-confidence fallback: what the deployment configures is NOT proof
    of what this commit ran.
  - **Other frameworks** (OpenCode/Claude/AtomCode) are identified by
    env/process-chain, but without their own session evidence the model is
    unknown — a specific model claim is rejected as unverifiable.
  - An operator pin (`PRAXIS_AUTHOR`/`PRAXIS_MODEL`) is a deliberate,
    trusted override, still not execution proof.
  Before writing a trailer, the agent MUST run
  `python scripts/py/detect_agent.py --json` and name the evidence-backed
  framework/model — do not read settings.yaml and paste its model.
- **Subject format is normalized**: lowercase start, no markdown (`**`/`` ` ``/`_`),
  no trailing period, ≤ 72 chars — plain text, never rendered markup.

| Part | Requirement |
|---|---|
| Subject | Conventional Commits: `type(scope): summary`; ≤ 72 chars; imperative mood |
| Body | Blank line after subject; explain **what** and **why** (structured Markdown: `## Sections`, `**keywords**`, `` `files` ``, `-` bullets) |
| Trailer | `Co-Authored-By:` line last, preceded by a blank line |

- Merge/revert commits are exempt (git-generated messages), but a dependabot
  merge is gated on diff scope — see `AGENTS.md` `## Dependency management`.
- **Commit-scan policy — single source of truth**: the Conventional-Commits
  contract (type whitelist, registered scopes, placeholder guard, branch-type
  policy) lives ONCE in `config/discovery/commits.yaml`, enforced by
  `scripts/py/commit_scan.py`. Python gates consume it directly; the Node hook
  uses the generated `config/discovery/commits.json` mirror refreshed by
  `scripts/py/gen_commits_json.py`. All gates consume the same contract — `.githooks/commit-msg`,
  `scripts/sh/verify-pr-merge.sh`, `scripts/py/generate_changelog.py`,
  `.github/workflows/pr-review.yml`. Never hardcode the type/scope list in a
  script; add a type/scope to `commits.yaml` and every gate learns it.
  `strict` mode rejects unknown scopes and CJK/empty placeholder subjects;
  `fix*` branches allow only `fix` commits (matches the accumulation-gate
  exemption).
- **Retired snapshot artifacts**: `config/discovery/commits.yaml` is the only
  commit-policy source. `config/discovery/commits.json` and
  `scripts/py/gen_commits_json.py` are intentionally absent and must not be
  reintroduced or referenced unless a JSON consumer is added in the same
  reviewed change.
- **Generated policy mirror**: after editing `config/discovery/commits.yaml`,
  run `python scripts/py/gen_commits_json.py` and include both the generator
  output and the YAML change in the same reviewed commit.
- **Hook mechanics**: `commit-msg` runs BEFORE the commit object exists, so
  HEAD still points at the previous commit; merge gates read `.git/MERGE_HEAD`
  (git removes it after commit), falling back to `HEAD^2` for manual post-merge
  commits. Detection triggers on the merged-tip **author** (`dependabot[bot]`)
  OR the message.
- **Bypass paths (forbidden unless justified)**: `--no-verify` skips ALL hooks;
  `PRAXIS_SKIP_AUTHOR_CHECK=1` skips message checks only. A `--no-verify`
  dependabot merge that drags in code MUST be reviewed by a second agent
  before push.
- **GPG signing is optional** — the GitCode project hook for GPG
  enforcement is NOT enabled on this repository (`Aplese/Praxis`), so
  unsigned commits are accepted. Keep `commit.gpgsign` off by default;
  signing is only required if a GitCode hook is later re-enabled.

## CompletionJudge — "done" is a machine verdict

Before declaring a task complete, run
`bash scripts/sh/verify-completion.sh` — the machine checks 11
dimensions (tests / coverage / net delta / doc-stats / lint /
dependency CVEs / complexity / import cycles / singleton drift /
CHANGELOG freshness / doc-index consistency). Only a `COMPLETE`
verdict authorizes "done"; `INCOMPLETE` returns the evidence gap and
the agent MUST continue working (ratchet property: a pass never
reopens). Every run is logged to `.praxis/judge-runs.jsonl` and the
aggregate dashboard to `docs/judge-stats.md` (see `judge-stats.sh`).
Full breakdown: `docs/architecture/completion-judge.md`.

## Remote PR merging (verify-pr-merge.sh)

- **Remote PRs (GitHub mirror) usually carry unsigned / non-conventional
  commits** — run `bash scripts/sh/verify-pr-merge.sh <branch>` BEFORE merging
  (signature + English Conventional-Commits subject + conflict pre-check). If
  it fails, **squash-merge** (`git merge --squash`) to one signed, English,
  conventional commit, or ask the author to rewrite the branch. Never merge
  unsigned commits and re-sign them afterwards — that rewrites history and
  force-pushes the mirror. Local agent branches are signed by construction.
- The PR gate also runs the sensitive-path hunk audit. Opaque full-file
  replacements (including multi-hunk rewrites) or deletions under
  `docs/roadmaps/` or `config/discovery/` fail closed with exit code 5; review
  the JSON report and merge only after both branch intents are checked.

## Mainline net-delta gate (enforced by `scripts/sh/verify-main-merge-gate.sh`, auto-run on `push-both.sh main`)

Main must not be inflated by repeated tiny commits. The gate computes the NET
code delta (added − deleted, code paths only; docs are exempt) of
`origin/main..main`, with three locks:

- **LOCK 1 — comment stripping**: added comment lines (per-extension
  markers) are subtracted from the delta; the gate counts REAL code, so
  padding a change with comments cannot pass.
- **LOCK 2 — symmetric deletion gate**: deletion-dominated changes are NOT
  an automatic exemption. Net deletions must accumulate to the same
  threshold (≥ 1000) as net additions; churning code (add + delete) to
  game the gate is rejected while still small.
- **LOCK 3 — hygiene ceiling**: if ≥ 60% of added lines are comments the
  change is rejected outright (comment padding is not engineering).

Thresholds: net < 600 → **reject**; 600 ≤ net < 1000 → **reject**;
net ≥ 1000 → **allow**; net ≤ 0 with deletions ≥ 1000 → **allow**
(symmetric removal); docs-only ≤ 5000 → **allow**. The agent must find
the best balance point between additions and removals — neither padding
with comments nor churning code passes; if neither side can reach the
threshold, STOP and ask the user.

On rejection it prints a worktree-accumulation hint and lists sibling
branches on the same merge-base so changes can be aligned before merging
(conflicts are reviewed by the merge Agent afterwards). Override the base
with `MAIN_BASE=<ref>` if `origin/main` is not the intended comparison.

### After a rejection — the required agent behavior (MANDATORY)

1. **Re-examine, do not shortcut**: review the work and ask "is it
   REALLY done?" — the gate rejected it for a reason; re-check against
   the CompletionJudge verdict and Definition of done before touching
   anything.
2. **Never self-waive**: do NOT bypass the gate with `MERGE_GATE_SKIP=1`
   (or any other bypass) on your own judgment. A waiver is the human's
   decision, not the agent's — if you believe the rejection is wrong,
   present the case and ask the user for explicit instruction.
3. **Keep accumulating on YOUR worktree branch**: continue committing on
   the same feature worktree branch you started from until the net delta
   qualifies (≥ 1000) and the gate passes — do not start a new branch
   from main to dodge the accumulation rule, and do not try alternate
   merge paths.
4. **Ask the user when growth stalls**: if the net delta cannot grow
   further (work is genuinely complete but below threshold), STOP and
   report to the user with an explicit question ("should this land
   despite being below the threshold?") — never decide for them.
5. **Every subsequent commit goes through the same gate** until it
   passes; a rejection is not a free pass for the next attempt.

## Push discipline (dual remotes)

- **Dual remotes**: `origin` = GitCode (`gitcode.com/Aplese/Praxis`,
  canonical); `github` = GitHub mirror (`guilingzhouyi-creator/Praxis`,
  CI carrier).
- **Local worktree branches push github/main directly — no PR required**:
  github/main has NO branch protection (removed), so `git push github main`
  from the local tree (main or any worktree) lands immediately. CI
  (`test.yml` matrix, `ci.yml`, `codeql.yml`, …) still runs on every push
  as a notification, not a merge gate. PRs (e.g. dependabot) are still
  handled through the normal PR flow.
- **Every push to main MUST go to BOTH remotes**: `git push origin main;
  git push github main` — **push origin (GitCode) FIRST**: it is the
  stricter gate (GPG pre-receive), so a rejection surfaces before anything
  is published on the mirror, avoiding a forced update. Pushing only to
  GitCode silently skips CI. Use `bash scripts/sh/push-both.sh main` (or
  `make push-both`).
- `push-both.sh main` additionally: auto-refreshes doc-stats (`make
  doc-stats` + commits drift), records a CompletionJudge run
  (`--skip=tests,coverage`), and refreshes the judge dashboard
  (`docs/judge-stats.md`) — all auto-committed with `--no-verify` and the
  AtomCode trailer.
