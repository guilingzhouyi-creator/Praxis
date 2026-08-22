#!/usr/bin/env bash
# Ensure hooks — enforce strict commit-msg for main and all worktrees.
#
# Guarantees:
#   - core.hooksPath is set to .githooks (relative, worktree-local)
#   - .githooks/commit-msg, pre-commit, post-checkout are executable
#   - commit.template points to .githooks/commit-template.txt when present
#   - every linked worktree inherits the same hooksPath and bits
#
# Usage:
#   bash scripts/sh/ensure-hooks.sh          # fix current repo + worktrees
#   bash scripts/sh/ensure-hooks.sh --check  # dry-run, exit 1 if drift
#
# Called from: Makefile `hooks` target and CI pre-flight.

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[ensure-hooks] ERROR: not inside a git repository" >&2
  exit 1
}
cd "$ROOT"

MODE="fix"
if [ "${1:-}" = "--check" ]; then
  MODE="check"
fi

HOOKS_DIR=".githooks"
TEMPLATE=".githooks/commit-template.txt"
FAIL=0

# ── 1. core.hooksPath ───────────────────────────────────────────────────
CURRENT="$(git config --get core.hooksPath 2>/dev/null || echo "")"
if [ "$CURRENT" != "$HOOKS_DIR" ]; then
  if [ "$MODE" = "check" ]; then
    echo "[ensure-hooks] ❌ core.hooksPath is '$CURRENT', expected '$HOOKS_DIR'" >&2
    FAIL=1
  else
    git config core.hooksPath "$HOOKS_DIR"
    echo "[ensure-hooks] ✅ core.hooksPath → $HOOKS_DIR"
  fi
else
  echo "[ensure-hooks] ✅ core.hooksPath=$HOOKS_DIR"
fi

# ── 2. Executable bits (tracked as 100755 in git index) ────────────────
for hook in commit-msg pre-commit post-checkout; do
  path="$HOOKS_DIR/$hook"
  if [ ! -f "$path" ]; then
    echo "[ensure-hooks] ⚠️  $path missing — skip" >&2
    continue
  fi
  if [ ! -x "$path" ]; then
    if [ "$MODE" = "check" ]; then
      echo "[ensure-hooks] ❌ $path not executable" >&2
      FAIL=1
    else
      chmod +x "$path"
      echo "[ensure-hooks] ✅ chmod +x $path"
    fi
  else
    echo "[ensure-hooks] ✅ $path executable"
  fi
  # Git index must also be 100755, not 100644 (worktree vs main drift).
  staged_mode="$(git ls-files --stage "$path" 2>/dev/null | awk '{print $1}' || echo "")"
  if [ -n "$staged_mode" ] && [ "$staged_mode" != "100755" ]; then
    if [ "$MODE" = "check" ]; then
      echo "[ensure-hooks] ❌ $path index mode $staged_mode, expected 100755" >&2
      FAIL=1
    else
      git update-index --chmod=+x "$path" 2>/dev/null || true
      echo "[ensure-hooks] ✅ git index chmod +x $path"
    fi
  fi
done

# ── 3. commit.template ─────────────────────────────────────────────────
if [ -f "$TEMPLATE" ]; then
  tmpl="$(git config --get commit.template 2>/dev/null || echo "")"
  if [ "$tmpl" != "$TEMPLATE" ]; then
    if [ "$MODE" = "check" ]; then
      echo "[ensure-hooks] ❌ commit.template is '$tmpl', expected '$TEMPLATE'" >&2
      FAIL=1
    else
      git config commit.template "$TEMPLATE"
      echo "[ensure-hooks] ✅ commit.template → $TEMPLATE"
    fi
  else
    echo "[ensure-hooks] ✅ commit.template=$TEMPLATE"
  fi
fi

# ── 4. Worktree inheritance ────────────────────────────────────────────
if command -v git >/dev/null 2>&1 && git worktree list --porcelain 2>/dev/null | grep -q "^worktree "; then
  while IFS= read -r line; do
    case "$line" in
      "worktree "*)
        wt="${line#worktree }"
        # Skip the main worktree (already handled above).
        if [ "$wt" = "$ROOT" ]; then
          continue
        fi
        wt_hooks="$(git -C "$wt" config --get core.hooksPath 2>/dev/null || echo "")"
        if [ "$wt_hooks" != "$HOOKS_DIR" ]; then
          if [ "$MODE" = "check" ]; then
            echo "[ensure-hooks] ❌ worktree $wt core.hooksPath='$wt_hooks', expected '$HOOKS_DIR'" >&2
            FAIL=1
          else
            git -C "$wt" config core.hooksPath "$HOOKS_DIR" 2>/dev/null || true
            echo "[ensure-hooks] ✅ worktree $wt core.hooksPath → $HOOKS_DIR"
          fi
        fi
        for hook in commit-msg pre-commit post-checkout; do
          p="$wt/$HOOKS_DIR/$hook"
          if [ -f "$p" ] && [ ! -x "$p" ]; then
            if [ "$MODE" = "check" ]; then
              echo "[ensure-hooks] ❌ worktree $wt $HOOKS_DIR/$hook not executable" >&2
              FAIL=1
            else
              chmod +x "$p" 2>/dev/null || true
              echo "[ensure-hooks] ✅ chmod +x $wt/$HOOKS_DIR/$hook"
            fi
          fi
        done
        ;;
    esac
  done < <(git worktree list --porcelain 2>/dev/null)
fi

if [ "$MODE" = "check" ] && [ "$FAIL" -ne 0 ]; then
  echo "[ensure-hooks] ❌ drift detected — run: bash scripts/sh/ensure-hooks.sh" >&2
  exit 1
fi

echo "[ensure-hooks] OK — all hooks strict and worktree-inherited."
