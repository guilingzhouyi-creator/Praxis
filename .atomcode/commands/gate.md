Run the pre-merge governance gates (lint + hooks + system boundaries) before merging into main.

## Usage

```
/gate
```

## What it runs

1. `make precommit` — pre-commit hooks (ruff, size check, mainline whitelist)
2. `bash scripts/sh/gate-merge.sh local` — local-merge gate (CompletionJudge + net-delta)
3. `make system-boundaries` — three-runtime import isolation check

## Examples

```
/gate  # Run all three gates; report pass/fail per gate
```
