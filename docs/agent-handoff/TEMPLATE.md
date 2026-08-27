# <Domain> Alignment Report — <date>

> Copy this template into `docs/agent-handoff/<domain>-<date>.md` when you
> finish a milestone or touch shared files. Keep `ALIGNMENT.md`'s change log
> updated in the same commit.

## Handoff (this agent → next agent)

- **Domain / worktree / branch**:
  - domain: K / M / S / T / C / B / A / infra
  - worktree: `praxis-<area>` · branch: `feature/<agent>-<area>`
- **What landed** (commit range merged to main):
  - `..` (e.g. `bd800342..0bec4785`)
- **What's in flight** (unmerged work on the branch):
  - ...
- **Shared files touched** (MUST be registered in `ALIGNMENT.md` change log):
  - e.g. `scripts/sh/gate-merge.sh completion` — coverage WSL serial (XDIST_ARGS)
- **Gotchas / conventions discovered** (for the next agent):
  - e.g. WSL worktree git resolves via Git Bash, not WSL; infra merges can
    clobber shared-script optimizations — check `git log --oneline <file>`
- **Next steps** (for the continuing agent):
  - ...
