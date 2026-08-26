#!/usr/bin/env bash
# Rotate docs/agent-handoff growth — archive old ALIGNMENT change-log
# entries and dated alignment reports once they exceed thresholds.
#
# Usage: bash scripts/sh/handoff-rotate.sh
#   (run manually, or when the push-both notice appears; never auto-runs
#   inside a gate so the resulting file changes are committed deliberately)
#
# Thresholds (env-overridable):
#   HANDOFF_LOG_MAX    change-log entries before rotation (default 30)
#   HANDOFF_KEEP       entries kept after rotation        (default 30)
#   HANDOFF_REPORT_MAX dated reports before archiving     (default 20)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HA="${HANDOFF_DIR:-$ROOT/docs/agent-handoff}"
ARCH="$HA/archive"
LOG_MAX="${HANDOFF_LOG_MAX:-30}"
KEEP="${HANDOFF_KEEP:-30}"
REPORT_MAX="${HANDOFF_REPORT_MAX:-20}"

mkdir -p "$ARCH"
CHANGED=0

# 1. Rotate ALIGNMENT.md change-log entries (newest KEEP survive; the rest
#    move to an archive file for traceability).
ALIGN="$HA/ALIGNMENT.md"
ENTRIES="$(grep -c '^| 202[0-9]-' "$ALIGN" 2>/dev/null || true)"
if [ "${ENTRIES:-0}" -gt "$LOG_MAX" ]; then
  ARCH_FILE="$ARCH/ALIGNMENT-$(date +%Y-%m).md"
  if [ ! -f "$ARCH_FILE" ]; then
    echo "# Archived alignment change-log ($(date +%Y-%m))" > "$ARCH_FILE"
    echo "" >> "$ARCH_FILE"
    echo "| Date | File | Agent | Change | Status |" >> "$ARCH_FILE"
    echo "|---|---|---|---|---|" >> "$ARCH_FILE"
  fi
  grep '^| 202[0-9]-' "$ALIGN" | head -n $((ENTRIES - KEEP)) >> "$ARCH_FILE"
  # Rewrite ALIGNMENT.md: header + table header + newest KEEP rows + tail
  # sections (Clobber warnings etc.) survive; rotated rows are removed.
  awk -v keep="$KEEP" '
    BEGIN { kept = 0; in_tail = 0 }
    /^## Clobber warnings/ {
      start = kept - keep; if (start < 0) start = 0
      for (i = start; i < kept; i++) print rows[i]
      in_tail = 1
      print
      next
    }
    in_tail { print; next }
    /^\| 202[0-9]-/ { rows[kept++] = $0; next }
    { print }
    END {
      if (!in_tail) {
        start = kept - keep; if (start < 0) start = 0
        for (i = start; i < kept; i++) print rows[i]
      }
    }
  ' "$ALIGN" > "$ALIGN.tmp" && mv "$ALIGN.tmp" "$ALIGN"
  CHANGED=1
  echo "rotated $((ENTRIES - KEEP)) ALIGNMENT entries -> $ARCH_FILE"
fi

# 2. Archive dated alignment reports (TEMPLATE copies) beyond REPORT_MAX.
REPORTS="$(find "$HA" -maxdepth 1 -name '*.md' ! -name 'README.md' ! -name 'ALIGNMENT.md' ! -name 'TEMPLATE.md' | sort)"
RCOUNT="$(printf '%s\n' "$REPORTS" | grep -c . || true)"
if [ "${RCOUNT:-0}" -gt "$REPORT_MAX" ]; then
  TO_MOVE="$((RCOUNT - REPORT_MAX))"
  printf '%s\n' "$REPORTS" | head -n "$TO_MOVE" | while read -r r; do
    mv "$r" "$ARCH/"
    echo "archived report: $(basename "$r")"
  done
  CHANGED=1
fi

if [ "$CHANGED" = "0" ]; then
  echo "handoff area within thresholds (${ENTRIES:-0} log entries, ${RCOUNT:-0} reports)"
fi
